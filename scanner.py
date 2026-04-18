import yfinance as yf
import pandas as pd
import requests
from bs4 import BeautifulSoup
from recommendation_engine import RecommendationEngine
import time
from datetime import datetime
from notifier import send_telegram_alert

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

    def get_mid_cap_tickers(self) -> list:
        return self._fetch_wikipedia_tickers("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies")

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

    def run_scan(self) -> list:
        """Deep Scan: Mid & Small Cap momentum leaders with Telegram Alerts"""
        print("Initializing Deep Market Scan (Mid & Small Caps)...")
        
        # 1. Fetch Universal Lists
        mid_list = self.get_mid_cap_tickers()
        small_list = self.get_small_cap_tickers()
        total_universe = mid_list + small_list
        
        if not total_universe:
            print("Error: Universal list empty. Falling back to core tickers.")
            total_universe = ["IWM", "MDY", "VTI", "PLTR", "SOFI", "U", "CHPT", "DKNG"]

        print(f"Universe identified: {len(mid_list)} Mid-Caps, {len(small_list)} Small-Caps.")
        
        # 2. Optimized Activity Check
        print(f"Filtering {len(total_universe)} stocks for activity leaders...")
        vol_data = self._batch_fetch_volume(total_universe)
        
        ranked_mid = [(t, vol_data[t]) for t in mid_list if t in vol_data]
        ranked_small = [(t, vol_data[t]) for t in small_list if t in vol_data]
        
        # Sort by volume and pick top 100 of each
        top_mid = [t[0] for t in sorted(ranked_mid, key=lambda x: x[1], reverse=True)[:100]]
        top_small = [t[0] for t in sorted(ranked_small, key=lambda x: x[1], reverse=True)[:100]]
        active_universe = top_mid + top_small
        
        print(f"Active Universe focused to {len(active_universe)} leaders.")
        
        # 3. Momentum Scan (The "Math Hunter")
        print("Running Momentum Hunter (60d trend)...")
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
        print(f"Top 10 candidates identified: {[p['symbol'] for p in top_picks]}")
        for pick in top_picks:
            symbol = pick['symbol']
            print(f"  AI Validating: {symbol}...")
            # Run the full AI engine (with Visual Intelligence)
            rec = self.engine.analyze_stock(symbol, bypass_cache=True, save_to_db=False)
            if rec:
                findings.append(rec)
                # TELEGRAM NOTIFICATION
                print(f"  Sending Telegram Alert for {symbol}...")
                send_telegram_alert(
                    symbol=rec['symbol'],
                    recommendation=rec['recommendation'],
                    conviction=rec['conviction'],
                    reasoning=rec['reasoning'],
                    price=rec.get('entry_price')
                )
            time.sleep(1) # Rate limit safety
            
        return findings

if __name__ == "__main__":
    scanner = MarketScanner()
    results = scanner.run_scan()
