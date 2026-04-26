import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from recommendation_engine import RecommendationEngine
import time
from datetime import datetime
from notifier import send_telegram_alert, send_bulk_discovery_alert

class MarketScanner:
    def __init__(self):
        self.engine = RecommendationEngine()
        self.headers = {"User-Agent": "Mozilla/5.0"}
        
    def _fetch_wikipedia_tickers(self, url) -> list:
        """Helper to scrape Wikipedia constituents tables"""
        try:
            r = requests.get(url, headers=self.headers)
            soup = BeautifulSoup(r.text, 'html.parser')
            table = soup.find('table', {'id': 'constituents'})
            if not table:
                table = soup.find('table', class_='wikitable')
            
            if not table: return []
            
            tickers = []
            for row in table.find_all('tr'):
                cols = row.find_all('td')
                if cols:
                    ticker = cols[0].text.strip().split('\n')[0].replace('.', '-')
                    tickers.append(ticker)
            return tickers
        except Exception as e:
            print(f"Scrape error for {url}: {e}")
            return []

    def get_small_cap_tickers(self) -> list:
        return self._fetch_wikipedia_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies")

    def _batch_fetch_volume(self, tickers, batch_size=100) -> dict:
        """Fetch 1-day volume in batches to prevent timeouts/errors"""
        activity_results = {}
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            print(f"  Downloading activity for batch {i//batch_size + 1} ({len(batch)} tickers)...")
            try:
                data = yf.download(batch, period="1d", group_by='ticker', progress=False)
                for ticker in batch:
                    try:
                        # For multi-index data from yf.download(batch)
                        if ticker in data.columns.levels[0]:
                            ticker_data = data[ticker]
                            if not ticker_data.empty and 'Volume' in ticker_data.columns:
                                vol = ticker_data['Volume'].iloc[-1]
                                activity_results[ticker] = float(vol)
                    except: continue
            except Exception as e:
                print(f"Batch error: {e}")
            time.sleep(0.5) # Brief pause between batches
        return activity_results

    def _should_scan(self) -> dict:
        """Check market regime before scanning. Skip in extreme bear markets."""
        try:
            regime = self.engine._get_market_regime()
            if regime.get("trend") == "BEAR" and regime.get("vix", 20) > 35:
                return {"scan": False, "regime": regime, "reason": "BEAR market + VIX > 35 — cash is king."}
            return {"scan": True, "regime": regime}
        except:
            return {"scan": True, "regime": {"trend": "UNKNOWN", "vix": 20, "multiplier": 0.75}}

    def run_scan(self, progress_callback=None) -> list:
        """Deep Scan: Mid & Small Cap momentum leaders with Telegram Alerts"""
        def update_status(msg):
            print(msg)
            if progress_callback:
                progress_callback(msg)

        # ── Regime Gate: bail out in extreme bear conditions ──────────────
        regime_check = self._should_scan()
        if not regime_check["scan"]:
            reason = regime_check.get("reason", "Market conditions unfavorable.")
            update_status(f"⚠️ SCAN SKIPPED: {reason}")
            if progress_callback:
                progress_callback(f"Scan aborted: {reason}")
            # Send notification instead of running scan
            try:
                from notifier import send_telegram_alert
                regime = regime_check["regime"]
                send_telegram_alert(
                    f"🛑 <b>Market Discovery Paused</b>\n"
                    f"Regime: {regime.get('trend')} | VIX: {regime.get('vix')}\n"
                    f"Breadth: {regime.get('breadth', 'N/A')} | Credit: {regime.get('credit', 'N/A')}\n"
                    f"Action: Cash preservation mode. No new scans."
                )
            except: pass
            return []

        update_status(f"Initializing Deep Market Scan (Regime: {regime_check['regime'].get('trend')}, VIX: {regime_check['regime'].get('vix')})...")
        
        # 1. Fetch Universal Lists
        small_list = self.get_small_cap_tickers()
        total_universe = small_list
        
        if not total_universe:
            print("Error: Universal list empty. Falling back to core tickers.")
            total_universe = ["IWM", "MDY", "VTI", "PLTR", "SOFI", "U", "CHPT", "DKNG"]

        update_status(f"Universe identified: {len(small_list)} Small-Cap candidates.")
        
        # 2. Optimized Activity Check
        update_status(f"Filtering {len(total_universe)} stocks for activity leaders...")
        vol_data = self._batch_fetch_volume(total_universe)
        
        ranked_small = [(t, vol_data[t]) for t in small_list if t in vol_data]
        
        # Sort by volume and pick top 200 (wider net for micro-caps)
        active_universe = [t[0] for t in sorted(ranked_small, key=lambda x: x[1], reverse=True)[:200]]
        
        update_status(f"Active Universe focused to {len(active_universe)} leaders.")
        
        # 3. Momentum Scan (The "Math Hunter")
        update_status("Running Momentum Hunter (60d trend)...")
        momentum_data = yf.download(active_universe, period="60d", group_by='ticker', progress=False)
        
        candidates = []
        for ticker in active_universe:
            try:
                if ticker not in momentum_data.columns.levels[0]: continue
                hist = momentum_data[ticker]
                if len(hist) < 20: continue
                
                current_price = hist['Close'].iloc[-1]
                sma50 = hist['Close'].tail(50).mean()
                
                # Filter: Must be in a confirmed uptrend
                if current_price < sma50: continue
                
                # Filter: Volume Surge (vs 20-day avg)
                avg_vol = hist['Volume'].tail(20).mean()
                current_vol = hist['Volume'].iloc[-1]
                vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
                
                # Score based on Volume Surge and 5-day Momentum
                ret_5d = (current_price - hist['Close'].iloc[-5]) / hist['Close'].iloc[-5] if len(hist) > 5 else 0
                score = (ret_5d * 0.6) + (vol_ratio * 0.4)
                
                candidates.append({"symbol": ticker, "score": score})
            except:
                continue
                
        candidates.sort(key=lambda x: x['score'], reverse=True)
        top_picks = candidates[:10]
        
        # 4. AI Deep-Dive & Telegram Alerts
        findings = []
        update_status(f"Top 10 candidates identified: {[p['symbol'] for p in top_picks]}")
        for pick in top_picks:
            symbol = pick['symbol']
            update_status(f"  AI Validating: {symbol}...")
            # Run the full AI engine (with Visual Intelligence) - Now saving to DB for AutoTrader
            rec = self.engine.analyze_stock(symbol, bypass_cache=True, save_to_db=True)
            if rec:
                findings.append(rec)
            time.sleep(1) # Rate limit safety
            
        # 5. CUMULATIVE TELEGRAM NOTIFICATION
        if findings:
            update_status(f"Scan complete. Sending cumulative alert for {len(findings)} candidates...")
            send_bulk_discovery_alert(findings)
            
        # ── Managed Fund: Autonomous Trading Trigger ───────────────────────
        try:
            update_status("🤖 Autonomous Fund: Processing trades based on new scan results...")
            from auto_trader import AutoTrader
            trader = AutoTrader(self.engine.db)
            trader.sync_portfolio_equity()
            trader.manage_existing_positions()
            trader.process_new_recommendations()
            trader.sync_portfolio_equity()
            update_status("🤖 Autonomous Fund: Trading cycle complete.")
        except Exception as e:
            update_status(f"⚠️ Autonomous Fund error: {e}")

        return findings

    def run_premarket_scan(self, progress_callback=None):
        """Specialized scan for high-momentum 'gappers' (>3% pre-market gap)."""
        def update_status(msg):
            print(f"[Pre-Market Scanner] {msg}")
            if progress_callback: progress_callback(msg)

        update_status("Starting Pre-Market Gap Discovery...")
        
        # 1. Fetch S&P 600 Candidates
        sp600_tickers = self.get_small_cap_tickers()
        
        # 2. Bulk Fetch Current OHLC for Gap Analysis
        update_status(f"Analysing gap potential for {len(sp600_tickers)} leaders...")
        momentum_data = yf.download(sp600_tickers, period="2d", interval="1d", group_by='ticker', threads=True)
        
        gappers = []
        for ticker in sp600_tickers:
            try:
                hist = momentum_data[ticker]
                if len(hist) < 2: continue
                
                prev_close = hist['Close'].iloc[-2]
                current_open = hist['Open'].iloc[-1]
                
                # Calculate Gap %
                gap_pct = ((current_open - prev_close) / prev_close) * 100
                
                if gap_pct >= 3.0: # Significant gap
                    gappers.append({
                        "symbol": ticker,
                        "gap": gap_pct,
                        "volume_surge": hist['Volume'].iloc[-1] / hist['Volume'].iloc[-2] if hist['Volume'].iloc[-2] > 0 else 1
                    })
            except: continue

        # 3. Sort by Gap Size & Volume Surge
        gappers.sort(key=lambda x: (x['gap'] * 0.7 + x['volume_surge'] * 0.3), reverse=True)
        top_gappers = gappers[:8] 

        if not top_gappers:
            update_status("No significant pre-market gaps found today.")
            return []

        # 4. AI Deep-Dive & Alerts
        findings = []
        update_status(f"AI Deep-Dive for {len(top_gappers)} top gappers...")
        for pick in top_gappers:
            symbol = pick['symbol']
            update_status(f"  Analysing Gapper: {symbol} (+{pick['gap']:.1f}% Gap)...")
            # Analysing Gapper - Now saving to DB for AutoTrader
            rec = self.engine.analyze_stock(symbol, bypass_cache=True, save_to_db=True)
            if rec:
                findings.append(rec)
            time.sleep(1)

        if findings:
            send_bulk_discovery_alert(findings)
            
        # ── Managed Fund: Autonomous Trading Trigger ───────────────────────
        try:
            update_status("🤖 Autonomous Fund (Pre-market): Processing trades...")
            from auto_trader import AutoTrader
            trader = AutoTrader(self.engine.db)
            trader.sync_portfolio_equity()
            trader.process_new_recommendations()
            trader.sync_portfolio_equity()
        except: pass

        return findings

if __name__ == "__main__":
    scanner = MarketScanner()
    results = scanner.run_scan()
