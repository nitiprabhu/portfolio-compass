#!/usr/bin/env python3
"""
PRODUCTION-READY STOCK RECOMMENDATION ENGINE
For "Portfolio Compass" - Startup MVP

Key changes from POC:
1. Structured JSON output (not just text)
2. Batch analysis (5-10 stocks at a time)
3. Database tracking (store all recommendations)
4. Outcome tracking (did it actually work?)
5. Simplified output (client-friendly explanations)
"""

import os
import json
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import yfinance as yf
import pandas as pd
import anthropic
from database import RecommendationDB
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

# ============================================================================
# RECOMMENDATION ENGINE
# ============================================================================

class RecommendationEngine:
    """Main engine that generates recommendations"""
    
    def __init__(self, db_path: str = "recommendations.db"):
        # Load .env file if it exists
        if os.path.exists(".env"):
            with open(".env") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        # Only set if not already set by env vars
                        if k not in os.environ:
                            os.environ[k] = v
        
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.db_path = db_path
        self.db = RecommendationDB(db_path)

        # Load learned layer weights from feedback loop (if available)
        try:
            from signal_calibrator import SignalCalibrator
            self._calibrator = SignalCalibrator(self.db)
            self._layer_weights = self._calibrator.get_current_weights()
            if self._layer_weights.get("source") == "learned":
                print(f"🧠 [Engine] Loaded learned weights (n={self._layer_weights['n_samples']}, acc={self._layer_weights['accuracy']:.1%})")
            else:
                print("🧠 [Engine] Using default equal weights (not enough training data yet).")
        except Exception as e:
            print(f"⚠️ [Engine] Calibrator not available, using equal weights: {e}")
            self._layer_weights = {
                "w_trend": 1.0, "w_momentum": 1.0, "w_volatility": 1.0,
                "w_volume": 1.0, "w_rs": 1.0, "w_guards": 1.0, "source": "default"
            }
    
    def analyze_stock(self, symbol: str, bypass_cache: bool = False, save_to_db: bool = True, 
                     market_mood: Optional[str] = None, mood_history: Optional[List[Dict]] = None) -> Optional[Dict]:
        """
        Analyze a stock and return structured recommendation
        
        Returns:
        {
            "symbol": "AAPL",
            "recommendation": "BUY",
            "conviction": 72,
            "entry_price": 150,
            "stop_loss": 130,
            "target_price": 180,
            "fundamentals_score": 11,
            "technical_score": 4,
            "reasoning": "...",
            "reasons": ["...", "..."],
            "risks": ["...", "..."],
            "outlook": "...",
            "similar_pattern": "..."
        }
        """
        
        try:
            # 1. Deduplication Check
            if not bypass_cache:
                last_rec = self.db.get_last_recommendation(symbol)
                if last_rec:
                    created_at = datetime.strptime(last_rec["created_at"], "%Y-%m-%d %H:%M:%S")
                    if datetime.now() - created_at < timedelta(hours=24):
                        print(f"Skipping {symbol}: Already analyzed recently ({last_rec['recommendation']}).")
                        return last_rec

            # 2. Get Data
            fundamentals = self._get_fundamentals(symbol)
            sector = fundamentals.get("sector", "Unknown")
            technicals = self._get_technicals(symbol, sector=sector)
            regime = self._get_market_regime()          # now returns Dict
            news = self._get_news(symbol)
            history = self._get_performance_history(symbol)
            port_stats = self._get_portfolio_stats()

            if "error" in technicals:
                print(f"Skipping {symbol}: Technical data error - {technicals['error']}")
                return None
            
            # Fundamentals are optional for backtests where history is often spotty
            if "error" in fundamentals:
                print(f"Proceeding with Tech-only analysis for {symbol} (Fundamentals missing)")
                fund_score = 5 # Neutral default
            else:
                fund_score = self._score_fundamentals(fundamentals)
            
            # 3. Score (with learned weights from feedback loop)
            tech_score = self._score_technicals(technicals, regime)   # pass regime dict

            # 4. Ask Claude for recommendation
            prompt = self._build_prompt(symbol, fundamentals, technicals, fund_score, tech_score,
                                        regime, news, history, port_stats, market_mood, mood_history)
            
            response = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )

            # Log Usage for Cost Analysis
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            # Claude Haiku costs: $0.25 / M input, $1.25 / M output
            cost = (input_tokens / 1_000_000 * 0.25) + (output_tokens / 1_000_000 * 1.25)
            self.db.log_api_usage(response.model, input_tokens, output_tokens, cost)

            recommendation_text = response.content[0].text
            

            # 5. Parse Claude's response
            rec = self._parse_recommendation(
                symbol,
                recommendation_text,
                fund_score,
                tech_score,
                fundamentals,
                technicals,
                news,
                save_to_db
            )

            # Attach ATR stop for UI display
            rec["atr_stop"] = technicals.get("atr_stop")
            rec["atr14"]    = technicals.get("atr14")

            # Attach tech layer snapshot for feedback loop
            rec["tech_layer_snapshot"] = technicals.get("_layer_snapshot")

            return rec

        
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
            return None
    
    def _get_fundamentals(self, symbol: str) -> Dict:
        """Fetch fundamentals with Piotroski F-Score, accruals, ROIC, insider activity, short interest."""
        try:
            ticker = yf.Ticker(symbol)
            info = getattr(ticker, 'info', {})
            
            # Handle cases where info is empty or returns an error from Yahoo (common for ETFs)
            if not info or 'quoteType' not in info:
                # If price exists, we keep going with minimal data so technicals can drive the decision
                hist = ticker.history(period="1d")
                if not hist.empty:
                    return {
                        "symbol": symbol,
                        "sector": "ETF/Fund",
                        "quote_type": "ETF",
                        "price": hist["Close"].iloc[-1],
                        "earnings_date": "N/A"
                    }
                return {"error": f"Could not fetch fundamentals for {symbol}"}

            base = {
                "symbol": symbol,
                "sector": info.get("sector", "Unknown"),
                "quote_type": info.get("quoteType", "EQUITY"),
                "price": info.get("currentPrice", 0),
                "roe": info.get("returnOnEquity"),
                "debt_equity": info.get("debtToEquity"),
                "peg": info.get("pegRatio"),
                "pe": info.get("trailingPE"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "profit_margin": info.get("profitMargins"),
                "fcf": info.get("freeCashflow"),
                "market_cap": info.get("marketCap"),
                "insider_ownership": info.get("insidersPercentHeld"),
                "earnings_date": str(ticker.calendar.get("Earnings Date", ["N/A"])[0]) if ticker.calendar is not None and "Earnings Date" in ticker.calendar else "N/A",
            }

            # ── Piotroski F-Score (9 signals) ────────────────────────────────
            base["piotroski_score"] = self._calculate_piotroski(ticker, info)

            # ── Earnings Quality: Accruals Ratio ─────────────────────────────
            try:
                net_income = info.get("netIncomeToCommon", 0) or 0
                operating_cf = info.get("operatingCashflow", 0) or 0
                total_assets = info.get("totalAssets", 0) or info.get("totalAssets", 1)
                if total_assets and total_assets > 0:
                    base["accruals_ratio"] = round((net_income - operating_cf) / total_assets, 4)
                else:
                    base["accruals_ratio"] = None
            except:
                base["accruals_ratio"] = None

            # ── ROIC (Return on Invested Capital) ─────────────────────────────
            try:
                ebit = info.get("ebitda", 0) or 0  # EBITDA as proxy
                total_assets_val = info.get("totalAssets", 0) or 0
                current_liabs = info.get("totalCurrentLiabilities", 0) or 0
                invested_capital = total_assets_val - current_liabs
                if invested_capital > 0:
                    base["roic"] = round(ebit * 0.79 / invested_capital, 4)  # 21% tax rate
                else:
                    base["roic"] = None
            except:
                base["roic"] = None

            # ── Insider Activity (net buys in last 90 days) ───────────────────
            try:
                insider_txns = ticker.insider_transactions
                if insider_txns is not None and not insider_txns.empty:
                    recent = insider_txns.head(20)  # Recent transactions
                    buys = recent[recent['Text'].str.contains('Purchase|Buy|Acquisition', case=False, na=False)].shape[0]
                    sells = recent[recent['Text'].str.contains('Sale|Sell|Disposition', case=False, na=False)].shape[0]
                    base["insider_net_buys"] = buys - sells
                else:
                    base["insider_net_buys"] = 0
            except:
                base["insider_net_buys"] = 0

            # ── Short Interest ─────────────────────────────────────────────────
            base["short_ratio"] = info.get("shortRatio")
            base["short_pct_float"] = info.get("shortPercentOfFloat")

            return base
        except Exception as e:
            return {"error": f"Fundamentals error for {symbol}: {str(e)}"}

    def _calculate_piotroski(self, ticker, info: Dict) -> int:
        """Calculate Piotroski F-Score (0-9) from Yahoo Finance data."""
        score = 0
        try:
            # 1. Positive ROA
            net_income = info.get("netIncomeToCommon", 0) or 0
            total_assets = info.get("totalAssets", 1) or 1
            roa = net_income / total_assets
            if roa > 0: score += 1

            # 2. Positive operating cash flow
            operating_cf = info.get("operatingCashflow", 0) or 0
            if operating_cf > 0: score += 1

            # 3. ROA improving (use returnOnAssets if available)
            roe_current = info.get("returnOnAssets")
            if roe_current and roe_current > 0:
                score += 1  # Simplified: current positive = pass

            # 4. Accruals: Operating CF > Net Income (quality of earnings)
            if operating_cf > net_income: score += 1

            # 5. Leverage decreasing (D/E < 1.0 = reasonable)
            debt_equity = info.get("debtToEquity")
            if debt_equity is not None and debt_equity < 100:  # Yahoo reports as percentage
                score += 1

            # 6. Current ratio > 1 (liquidity)
            current_ratio = info.get("currentRatio")
            if current_ratio is not None and current_ratio > 1.0: score += 1

            # 7. No dilution (shares outstanding not growing significantly)
            shares = info.get("sharesOutstanding", 0)
            float_shares = info.get("floatShares", 0)
            if shares and float_shares and float_shares / shares > 0.85:
                score += 1  # High float ratio = low dilution risk

            # 8. Gross margin positive
            gross_margin = info.get("grossMargins")
            if gross_margin is not None and gross_margin > 0: score += 1

            # 9. Asset turnover (revenue / total assets)
            revenue = info.get("totalRevenue", 0) or 0
            if total_assets > 0 and revenue / total_assets > 0.3:
                score += 1

        except Exception as e:
            print(f"Piotroski calc error: {e}")

        return score
    
    def _get_news(self, symbol: str) -> List[Dict]:
        """Fetch latest news for sentiment analysis (Filtered for high relevance)"""
        try:
            ticker = yf.Ticker(symbol)
            all_news = ticker.news
            if not all_news: return []
            
            # Get company name for better filtering
            company_name = ticker.info.get('longName', '').lower()
            
            filtered_news = []
            for n in all_news:
                title = n['content'].get('title', '').lower()
                # ONLY keep if symbol or company name is in title AND it's not a generic market brief
                is_relevant = symbol.lower() in title or (company_name and company_name in title)
                is_noise = "morning brief" in title or "daily roundup" in title or "top stock" in title
                
                if is_relevant and not is_noise:
                    filtered_news.append(n)
            
            return filtered_news[:5]
        except:
            return []

    def _get_performance_history(self, symbol: str) -> str:
        """Get past performance context for this symbol"""
        p = self.db._get_placeholder()
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT status, return_pct, check_date 
                    FROM outcomes 
                    WHERE symbol = {p} 
                    ORDER BY check_date DESC LIMIT 3
                """, (symbol,))
                rows = cursor.fetchall()
                if not rows:
                    return "No previous trading history for this asset."
                
                history = "RECENT HISTORY FOR THIS ASSET:\n"
                for status, ret, date in rows:
                    res = f"{ret:.1f}%" if ret is not None else "N/A"
                    history += f"- Status: {status} | Return: {res} | Date: {date}\n"
                return history
        except:
            return "History lookup failed."

    def _get_portfolio_stats(self) -> str:
        """Get high-level portfolio performance summary"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*), AVG(return_pct) FROM outcomes WHERE status != 'OPEN'")
                total, avg = cursor.fetchone()
                if not total:
                    return "Portfolio is brand new (0 closed trades)."
                
                return f"PORTFOLIO PERFORMANCE: {total} total closed trades with {avg or 0:.1f}% average return."
        except:
            return "Portfolio stats unavailable."

    def _get_market_regime(self) -> Dict:
        """Enhanced market regime: SPY trend + VIX + breadth + credit spread."""
        try:
            spy_hist = yf.Ticker("SPY").history(period="6mo")
            current = spy_hist["Close"].iloc[-1]
            sma50 = spy_hist["Close"].tail(50).mean()

            # VIX fear gauge
            try:
                vix_hist = yf.Ticker("^VIX").history(period="5d")
                vix = float(vix_hist["Close"].iloc[-1])
            except:
                vix = 20.0  # neutral default

            if current > sma50 * 1.02:
                trend = "BULL"
            elif current < sma50 * 0.98:
                trend = "BEAR"
            else:
                trend = "SIDEWAYS"

            # ── NEW: Market Breadth (RSP/SPY ratio) ──────────────────────
            # RSP = equal-weight S&P 500. If RSP lags SPY, only mega-caps are leading.
            breadth = "BROAD"
            try:
                rsp_hist = yf.Ticker("RSP").history(period="1mo")["Close"]
                spy_1mo = yf.Ticker("SPY").history(period="1mo")["Close"]
                if len(rsp_hist) >= 2 and len(spy_1mo) >= 2:
                    rsp_ret = rsp_hist.iloc[-1] / rsp_hist.iloc[0]
                    spy_ret = spy_1mo.iloc[-1] / spy_1mo.iloc[0]
                    breadth_ratio = rsp_ret / spy_ret
                    breadth = "BROAD" if breadth_ratio > 0.98 else "NARROW"
            except:
                breadth = "UNKNOWN"

            # ── NEW: Credit Spread (HYG/LQD ratio) ──────────────────────
            # HYG = high-yield bonds, LQD = investment-grade. Rising ratio = risk appetite.
            credit = "NEUTRAL"
            try:
                hyg_hist = yf.Ticker("HYG").history(period="1mo")["Close"]
                lqd_hist = yf.Ticker("LQD").history(period="1mo")["Close"]
                if len(hyg_hist) >= 2 and len(lqd_hist) >= 2:
                    credit_now = hyg_hist.iloc[-1] / lqd_hist.iloc[-1]
                    credit_start = hyg_hist.iloc[0] / lqd_hist.iloc[0]
                    credit = "RISK_ON" if credit_now > credit_start else "RISK_OFF"
            except:
                credit = "NEUTRAL"

            # ── Composite Regime Multiplier ──────────────────────────────
            if trend == "BULL" and vix < 20:
                multiplier = 1.0
            elif trend == "BULL" and vix < 25:
                multiplier = 0.85
            elif trend == "BEAR" and vix > 25:
                multiplier = 0.3
            elif trend == "BEAR":
                multiplier = 0.6
            else:
                multiplier = 0.75

            # Breadth adjustment: narrow rally = lower confidence
            if breadth == "NARROW" and trend == "BULL":
                multiplier *= 0.85  # Reduce confidence in narrow bull markets

            # Credit spread adjustment
            if credit == "RISK_OFF" and trend != "BEAR":
                multiplier *= 0.90  # Credit markets flagging caution

            return {
                "trend": trend, "vix": round(vix, 1), "multiplier": round(multiplier, 3),
                "breadth": breadth, "credit": credit
            }
        except:
            return {"trend": "SIDEWAYS", "vix": 20.0, "multiplier": 0.75, "breadth": "UNKNOWN", "credit": "NEUTRAL"}

    # Sector ETF mapping for sector-relative strength
    SECTOR_ETF_MAP = {
        "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV",
        "Energy": "XLE", "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
        "Industrials": "XLI", "Basic Materials": "XLB", "Real Estate": "XLRE",
        "Utilities": "XLU", "Communication Services": "XLC",
    }

    def _get_technicals(self, symbol: str, sector: str = "Unknown") -> Dict:
        """Fetch comprehensive technical metrics — Phase 2 expert upgrade."""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")

            if hist.empty:
                return {"error": f"No data for {symbol}"}

            close = hist["Close"]
            high  = hist["High"]
            low   = hist["Low"]
            volume = hist["Volume"]
            current = close.iloc[-1]

            # ── Trend: SMA 50 / 200 ──────────────────────────────────────────
            sma50  = close.tail(50).mean()
            sma200 = close.tail(200).mean() if len(close) >= 200 else None
            high52 = close.tail(252).max() if len(close) >= 252 else close.max()
            low52  = close.tail(252).min() if len(close) >= 252 else close.min()
            volatility  = close.pct_change().std() * (252 ** 0.5) * 100
            change_1y   = (current - close.iloc[0]) / close.iloc[0] * 100

            # Weekly SMA50 alignment check
            weekly_hist = ticker.history(period="1y", interval="1wk")
            weekly_sma50 = weekly_hist["Close"].tail(50).mean() if len(weekly_hist) >= 10 else None
            weekly_above_sma50 = float(weekly_hist["Close"].iloc[-1]) > weekly_sma50 if weekly_sma50 else None

            # ── Momentum: RSI (14) with Divergence ───────────────────────────
            delta = close.diff()
            gain  = delta.where(delta > 0, 0).rolling(14).mean()
            loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi_series = 100 - (100 / (1 + gain / loss))
            current_rsi = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0

            # RSI Divergence: price makes 20-day high but RSI lower than its prior peak
            price_new_high = current >= close.tail(20).max()
            rsi_20 = rsi_series.tail(20)
            rsi_divergence = False
            if price_new_high and len(rsi_20) >= 5:
                prior_rsi_peak = rsi_20.iloc[:-1].max()
                rsi_divergence = bool(current_rsi < prior_rsi_peak - 3)  # 3pt buffer

            # ── Momentum: MACD (12/26/9) ─────────────────────────────────────
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - signal_line
            macd_histogram = float(histogram.iloc[-1])
            macd_histogram_prev = float(histogram.iloc[-2]) if len(histogram) >= 2 else macd_histogram
            macd_slope = macd_histogram - macd_histogram_prev  # positive = accelerating
            macd_bullish = bool(macd_histogram > 0 and macd_slope > 0)

            # ── Volatility: ATR (14) for smart stop-loss ─────────────────────
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr14 = float(tr.rolling(14).mean().iloc[-1])
            atr_stop = round(current - 2.0 * atr14, 2)  # prop-desk standard

            # ── Fibonacci Retracement Levels ─────────────────────────────────
            fib_range = high52 - low52
            fib_levels = {
                "fib_382": high52 - (fib_range * 0.382),
                "fib_500": high52 - (fib_range * 0.500),
                "fib_618": high52 - (fib_range * 0.618)
            }
            # Check if price is near a major fib level (within 1%)
            near_fib = None
            for name, val in fib_levels.items():
                if abs(current - val) / val < 0.01:
                    near_fib = name

            # ── Volatility: Bollinger Bands + Squeeze ────────────────────────
            bb_mid   = close.rolling(20).mean()
            bb_std   = close.rolling(20).std()
            bb_upper = bb_mid + 2 * bb_std
            bb_lower = bb_mid - 2 * bb_std
            bb_width = float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_mid.iloc[-1])
            # Squeeze: BB width at 6-month (126-day) low?
            bb_width_series = (bb_upper - bb_lower) / bb_mid
            bb_squeeze = bool(bb_width <= bb_width_series.tail(126).min() * 1.05)

            # ── Volume: Ratio + Percentile + OBV + OBV Divergence ────────────
            avg_vol   = volume.tail(20).mean()
            vol_ratio = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0

            # Volume percentile: where today's volume ranks in last 60 days
            vol_60 = volume.tail(60)
            today_vol = float(volume.iloc[-1])
            vol_percentile = float((vol_60 < today_vol).sum() / len(vol_60) * 100) if len(vol_60) > 0 else 50.0

            obv = (volume * close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))).cumsum()
            obv_sma20 = obv.rolling(20).mean()
            obv_rising = bool(obv.iloc[-1] > obv_sma20.iloc[-1])
            # OBV divergence: price up but OBV flat/down
            price_up = close.iloc[-1] > close.tail(10).iloc[0]
            obv_divergence = bool(price_up and not obv_rising)

            # ── Consecutive direction ─────────────────────────────────────────
            diff_series = close.diff().fillna(0)
            consec_up   = int((diff_series[::-1] > 0).cumprod().sum())
            consec_down = int((diff_series[::-1] < 0).cumprod().sum())

            # ── Earnings Distance Guard ───────────────────────────────────────
            try:
                info = ticker.info
                earnings_ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
                if earnings_ts:
                    earnings_date = datetime.fromtimestamp(earnings_ts)
                    days_to_earnings = (earnings_date - datetime.now()).days
                else:
                    days_to_earnings = 99
            except:
                days_to_earnings = 99
            earnings_watch_only = bool(0 <= days_to_earnings <= 5)

            # ── Sector Relative Strength ──────────────────────────────────────
            sector_etf = self.SECTOR_ETF_MAP.get(sector)
            sector_rs = None
            if sector_etf:
                try:
                    stock_ret = (close.iloc[-1] / close.iloc[-20] - 1)
                    sect_hist = yf.Ticker(sector_etf).history(period="2mo")["Close"]
                    sect_ret  = (sect_hist.iloc[-1] / sect_hist.iloc[-20] - 1)
                    sector_rs = round(float(stock_ret - sect_ret) * 100, 2)  # % outperformance
                except:
                    sector_rs = None

            # ── RS vs SPY ─────────────────────────────────────────────────────
            rs_info = self._get_relative_strength(symbol)

            # ── Price Action Digests ──────────────────────────────────────────
            daily_digest = "DAILY OHLC (Last 20 Days):\n"
            for d, row in hist.tail(20).iterrows():
                daily_digest += f"{d.strftime('%Y-%m-%d')}: O:{row['Open']:.2f} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f} V:{row['Volume']:,.0f}\n"

            weekly_digest = "WEEKLY OHLC (Last 26 Weeks):\n"
            for d, row in weekly_hist.tail(26).iterrows():
                weekly_digest += f"{d.strftime('%Y-%m-%d')}: O:{row['Open']:.2f} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f}\n"

            return {
                # Core
                "symbol": symbol,
                "current_price": current,
                # Trend
                "sma_50": sma50, "sma_200": sma200,
                "high_52w": high52, "low_52w": low52,
                "above_sma50": current > sma50,
                "above_sma200": current > sma200 if sma200 else False,
                "weekly_above_sma50": weekly_above_sma50,
                # Momentum
                "rsi": current_rsi, "rsi_divergence": rsi_divergence,
                "macd_histogram": macd_histogram, "macd_slope": macd_slope, "macd_bullish": macd_bullish,
                "consec_up": consec_up, "consec_down": consec_down,
                # Volatility / Safety
                "volatility": volatility, "change_1y": change_1y,
                "atr14": round(atr14, 2), "atr_stop": atr_stop,
                "bb_width": round(bb_width, 4), "bb_squeeze": bb_squeeze,
                "fib_levels": fib_levels, "near_fib": near_fib,
                # Volume / Conviction
                "volume_ratio": vol_ratio,
                "volume_percentile": round(vol_percentile, 1),
                "obv_rising": obv_rising, "obv_divergence": obv_divergence,
                # Relative Strength
                "rs_current": rs_info.get("rs_current"),
                "rs_sma20":   rs_info.get("rs_sma20"),
                "rs_trend":   rs_info.get("rs_trend"),
                "sector_rs":  sector_rs,
                # Guards
                "days_to_earnings": days_to_earnings,
                "earnings_watch_only": earnings_watch_only,
                # Digests
                "daily_digest": daily_digest,
                "weekly_digest": weekly_digest,
            }
        except Exception as e:
            return {"error": f"Could not fetch technicals for {symbol}: {e}"}

    def _get_relative_strength(self, symbol: str, benchmark: str = "SPY", period: str = "6mo") -> Dict:
        """Calculate RS of a stock vs SPY benchmark."""
        try:
            stock = yf.Ticker(symbol).history(period=period)["Close"]
            bench = yf.Ticker(benchmark).history(period=period)["Close"]
            df = pd.concat([stock, bench], axis=1, keys=["stock", "bench"]).dropna()
            df["RS"] = df["stock"] / df["bench"]
            df["RS_SMA20"] = df["RS"].rolling(20).mean()
            cur_rs  = float(df["RS"].iloc[-1])
            cur_sma = float(df["RS_SMA20"].iloc[-1])
            trend = ("bullish" if cur_rs > 1 and cur_rs > cur_sma
                     else "bearish" if cur_rs < 1 and cur_rs < cur_sma
                     else "neutral")
            return {"rs_current": round(cur_rs, 4), "rs_sma20": round(cur_sma, 4), "rs_trend": trend}
        except:
            return {}
    
    def _score_fundamentals(self, fund: Dict) -> int:
        """Score fundamentals 0-18 using dynamic sector-aware thresholds + quality overlays"""
        if fund.get("quote_type") == "ETF":
            return 14  # Auto-pass fundamentals for ETFs so technicals drive the entire score
            
        revenue_growth = fund.get("revenue_growth") or 0
        pe = fund.get("pe")
        
        # Hyper-Growth Multi-Bagger Bypass
        if revenue_growth > 0.25 and (pe is None or pe < 0 or pe > 50):
            return 15  # Auto-pass fundamentals due to explosive growth characteristics

        score = 0
        sector = fund.get("sector", "Unknown")
        
        # Dynamic thresholds based on sector
        max_pe = 40 if sector == "Technology" else (15 if sector == "Financial Services" else 25)
        max_debt_equity = 1.5 if sector in ["Utilities", "Real Estate"] else 1.0
        min_roe = 0.10 if sector in ["Utilities", "Basic Materials"] else 0.15
        max_peg = 1.5 if sector == "Technology" else 1.0
        
        if (fund.get("roe") or 0) > min_roe:
            score += 1
        if (fund.get("debt_equity") or float('inf')) < max_debt_equity:
            score += 1
        peg = fund.get("peg")
        if peg is not None and peg < max_peg:
            score += 1
        pe = fund.get("pe")
        if pe is not None and 0 < pe < max_pe:
            score += 1
        if (fund.get("revenue_growth") or 0) > 0.15:
            score += 1
        if (fund.get("earnings_growth") or 0) > 0.10:
            score += 1
        if (fund.get("profit_margin") or 0) > 0.10:
            score += 1
        if (fund.get("insider_ownership") or 0) > 0.05:
            score += 1
        if (fund.get("market_cap") or 0) > 1_000_000_000:
            score += 1
        fcf = fund.get("fcf")
        if fcf is not None and fcf > 0:
            score += 1

        # ── NEW: Piotroski F-Score quality overlay ────────────────────────
        piotroski = fund.get("piotroski_score", 5)
        if piotroski >= 7:
            score += 2   # Strong financial health
        elif piotroski <= 3:
            score -= 2   # Weak financials — red flag

        # ── NEW: Earnings Quality (Accruals) ─────────────────────────────
        accruals = fund.get("accruals_ratio")
        if accruals is not None:
            if abs(accruals) < 0.05:
                score += 1   # Quality earnings backed by cash flow
            elif accruals > 0.10:
                score -= 1   # Aggressive accounting — earnings may not be real

        # ── NEW: ROIC (Capital Allocation) ───────────────────────────────
        roic = fund.get("roic")
        if roic is not None:
            if roic > 0.15:
                score += 2   # Capital compounder
            elif roic > 0.10:
                score += 1   # Acceptable return on capital

        # ── NEW: Insider Activity ────────────────────────────────────────
        insider_net = fund.get("insider_net_buys", 0)
        if insider_net > 0:
            score += 1   # Insiders are buying — skin-in-the-game
        elif insider_net < -3:
            score -= 1   # Heavy insider selling

        # ── NEW: Short Interest Risk Flag ────────────────────────────────
        short_pct = fund.get("short_pct_float")
        if short_pct is not None and short_pct > 0.15:
            score -= 1   # High short interest = elevated risk

        # Technical base (will be refined with technical scoring)
        score += 3
        
        return score
    
    def _score_technicals(self, tech: Dict, regime: Dict = None) -> float:
        """Expert-grade multi-layer scoring using learned weights from feedback loop.
        Each layer -2 to +2, weighted by calibrated coefficients, multiplied by regime factor.
        Final range: variable  →  mapped to signal."""
        if regime is None:
            regime = {"trend": "SIDEWAYS", "vix": 20.0, "multiplier": 0.75}
        regime_mult = regime.get("multiplier", 0.75)

        # Load learned weights
        w = self._layer_weights

        # ── Layer 1: Trend ──────────────────────────────────────────────────
        l1 = 0
        if tech.get("above_sma50"):  l1 += 1
        if tech.get("above_sma200"): l1 += 1
        # Weekly timeframe alignment: daily BUY with weekly below SMA50 = penalty
        if tech.get("weekly_above_sma50") is False: l1 -= 1
        # NEW: 52-week high proximity (within 5% of 52W high = breakout territory)
        current = tech.get("current_price", 0)
        high52 = tech.get("high_52w", 0)
        if high52 > 0 and current > 0 and (current / high52) > 0.95:
            l1 += 1  # Near 52W high — momentum breakout
        l1 = max(-2, min(2, l1))

        # ── Layer 2: Momentum ───────────────────────────────────────────────
        l2 = 0
        rsi = tech.get("rsi", 50)
        if 40 < rsi < 70:    l2 += 1   # Trend active but not exhausted
        elif rsi >= 70:      l2 -= 1   # Overbought
        elif rsi <= 30:      l2 += 2   # Strong Oversold (Reversal potential)
        if tech.get("rsi_divergence"): l2 -= 2  # Bearish divergence = distribution
        # MACD histogram slope
        if tech.get("macd_bullish"):   l2 += 1
        elif tech.get("macd_histogram", 0) < 0: l2 -= 1
        if tech.get("consec_up", 0) >= 3:   l2 += 1
        if tech.get("consec_down", 0) >= 3: l2 -= 1
        l2 = max(-2, min(2, l2))

        # ── Layer 3: Volatility / Safety ────────────────────────────────────
        l3 = 0
        if tech.get("bb_squeeze"): l3 += 1  # Imminent breakout setup
        if tech.get("near_fib"):   l3 += 1  # Price rejection/support at Fib level
        vol = tech.get("volatility", 30)
        if vol < 25: l3 += 1    # Low vol — manageable risk
        elif vol > 60: l3 -= 1  # Very high vol — dangerous
        l3 = max(-2, min(2, l3))

        # ── Layer 4: Volume / Conviction ────────────────────────────────────
        l4 = 0
        vol_ratio = tech.get("volume_ratio", 1.0)
        # NEW: Volume percentile (more robust than raw ratio)
        vol_percentile = tech.get("volume_percentile", 50)
        if vol_percentile > 90:   l4 += 2   # Top-decile volume — institutional interest
        elif vol_ratio > 1.2:     l4 += 1
        elif vol_ratio < 0.7:     l4 -= 1
        if tech.get("obv_rising"):      l4 += 1   # Institutions accumulating
        if tech.get("obv_divergence"): l4 -= 2   # Fake move — institutional exit
        l4 = max(-2, min(2, l4))

        # ── Layer 5: Relative Strength ──────────────────────────────────────
        l5 = 0
        rs_trend = tech.get("rs_trend")
        rs_current = tech.get("rs_current")
        if rs_current and rs_current > 1 and rs_trend == "bullish": l5 += 1
        elif rs_current and rs_current < 1 and rs_trend == "bearish": l5 -= 1
        # Sector RS: stock beating its sector ETF
        sect_rs = tech.get("sector_rs")
        if sect_rs is not None:
            if sect_rs > 2:   l5 += 1   # Out-performing sector by > 2%
            elif sect_rs < -2: l5 -= 1  # Under-performing sector
        l5 = max(-2, min(2, l5))

        # ── Layer 6: Guards / Risk Events ───────────────────────────────────
        l6 = 0
        if tech.get("earnings_watch_only"): l6 -= 2  # Earnings within 5 days
        l6 = max(-2, min(2, l6))

        # ── Weighted sum using learned weights ──────────────────────────────
        raw_score = (
            l1 * w.get("w_trend", 1.0) +
            l2 * w.get("w_momentum", 1.0) +
            l3 * w.get("w_volatility", 1.0) +
            l4 * w.get("w_volume", 1.0) +
            l5 * w.get("w_rs", 1.0) +
            l6 * w.get("w_guards", 1.0)
        )
        final_score = round(raw_score * regime_mult, 2)

        # Persist layer snapshot for feedback loop training
        tech["_layer_snapshot"] = {
            "l_trend": l1, "l_momentum": l2, "l_volatility": l3,
            "l_volume": l4, "l_rs": l5, "l_guards": l6,
            "regime_mult": regime_mult, "raw_score": raw_score, "final_score": final_score
        }

        # Map to legacy 0-5 int for backward-compatibility with DB/UI
        # Strong BUY (>=5) → 5, BUY (3-4) → 4, HOLD → 3, WEAK → 1-2, AVOID → 0
        tech["_raw_score"] = final_score  # stash for prompt
        if final_score >= 5:   return 5
        elif final_score >= 3: return 4
        elif final_score >= 1: return 3
        elif final_score >= -1: return 2
        elif final_score >= -3: return 1
        else:                  return 0
    
    def _build_prompt(self, symbol: str, fund: Dict, tech: Dict, fund_score: int, tech_score: int,
                     regime: Dict, news: List[Dict], history: str, port_stats: str, 
                     market_mood: Optional[str] = None, mood_history: Optional[List[Dict]] = None) -> str:
        """Build expert-grade prompt using all enhanced indicators."""
        news_text = "\n".join([f"- {n['content']['title']}: {n['content'].get('summary', '')}" for n in news])
        market_regime = regime.get("trend", "SIDEWAYS")
        vix = regime.get("vix", 20.0)

        # Earnings warning
        earnings_note = ""
        if tech.get("earnings_watch_only"):
            earnings_note = f"\n⚠️ EARNINGS IN {tech.get('days_to_earnings')} DAYS — Downgrade any BUY to WATCH unless this is an earnings play."

        # ATR stop-loss override
        atr_stop_note = f"ATR-based Stop-Loss: ${tech.get('atr_stop', 'N/A')} (Entry - 2×ATR14={tech.get('atr14','N/A')})"

        # MACD description
        macd_desc = "Bullish (histogram positive & rising)" if tech.get("macd_bullish") else (
            "Bearish" if tech.get("macd_histogram", 0) < 0 else "Neutral (decelerating)")

        # RSI divergence warning
        rsi_div_note = "⚠️ BEARISH RSI DIVERGENCE DETECTED — price at 20-day high but RSI lower than prior peak. Potential distribution." if tech.get("rsi_divergence") else ""

        # OBV note
        obv_note = "⚠️ OBV DIVERGENCE — price rising but OBV flat/falling. Institutional exit signal." if tech.get("obv_divergence") else (
            "OBV rising — institutional accumulation confirmed." if tech.get("obv_rising") else "")

        # BB squeeze
        bb_note = "🔔 BOLLINGER BAND SQUEEZE ACTIVE — breakout imminent. Direction TBD by volume." if tech.get("bb_squeeze") else ""

        # Weekly alignment
        weekly_align = "ALIGNED" if tech.get("weekly_above_sma50") else ("MISALIGNED (daily BUY contradicts weekly)" if tech.get("weekly_above_sma50") is False else "N/A")

        # Sector RS
        sect_rs = tech.get("sector_rs")
        sect_rs_note = f"{sect_rs:+.1f}% vs sector ETF" if sect_rs is not None else "N/A"

        # Piotroski & quality notes
        piotroski = fund.get("piotroski_score", "N/A")
        accruals = fund.get("accruals_ratio", "N/A")
        roic = fund.get("roic", "N/A")
        insider_net = fund.get("insider_net_buys", 0)
        insider_note = f"Net insider {'buys' if insider_net > 0 else 'sells'}: {abs(insider_net)}" if insider_net != 0 else "No recent insider activity"
        short_pct = fund.get("short_pct_float")
        short_note = f"{short_pct*100:.1f}% of float" if short_pct else "N/A"

        # 52W proximity
        pct_from_high = round((tech.get("current_price", 0) / tech.get("high_52w", 1) * 100), 1) if tech.get("high_52w") else "N/A"

        # Regime details
        breadth = regime.get("breadth", "UNKNOWN")
        credit = regime.get("credit", "NEUTRAL")

        # Layer weights info
        weight_source = self._layer_weights.get("source", "default")
        weight_note = f"(Source: {weight_source})" if weight_source == "learned" else "(Equal weights — awaiting calibration data)"

        return f"""
Analyze {symbol} and provide a precise recommendation. Use ALL data below.
{earnings_note}

FUNDAMENTALS — Score: {fund_score}/18
- Sector: {fund.get('sector', 'Unknown')}
- ROE: {fund.get('roe', 'N/A')} | P/E: {fund.get('pe', 'N/A')} | PEG: {fund.get('peg', 'N/A')}
- D/E: {fund.get('debt_equity', 'N/A')} | Revenue growth: {fund.get('revenue_growth', 'N/A')}
- Profit margin: {fund.get('profit_margin', 'N/A')}
- Piotroski F-Score: {piotroski}/9 | Accruals Ratio: {accruals} | ROIC: {roic}
- Insider Activity: {insider_note} | Short Interest: {short_note}

TECHNICAL SNAPSHOT — Score: {tech_score}/5 (Raw: {tech.get('_raw_score', 'N/A')}) {weight_note}
• Price:        ${tech.get('current_price', 0):.2f}  ({pct_from_high}% of 52W high)
• SMA50/200:    ${tech.get('sma_50', 0):.2f} / ${tech.get('sma_200') or 0:.2f}  (Weekly alignment: {weekly_align})
• RSI(14):      {tech.get('rsi', 0):.1f}  {rsi_div_note}
• MACD:         {macd_desc}  (histogram={tech.get('macd_histogram',0):.3f}, slope={tech.get('macd_slope',0):.3f})
• Volume:       {tech.get('volume_ratio',0):.2f}x 20-day avg  (Percentile: {tech.get('volume_percentile', 50):.0f}/100)  |  {obv_note}
• Volatility:   {tech.get('volatility',0):.1f}% annualised  |  {atr_stop_note}
• BB Width:     {tech.get('bb_width',0):.4f}  |  {bb_note}
• RS vs SPY:    {tech.get('rs_current','N/A')} ({tech.get('rs_trend','N/A')})
• Sector RS:    {sect_rs_note}
• Consec days:  {tech.get('consec_up',0)} up / {tech.get('consec_down',0)} down
• 52W range:    ${tech.get('low_52w',0):.2f} – ${tech.get('high_52w',0):.2f}
• 1Y return:    {tech.get('change_1y',0):.1f}%

MARKET REGIME: {market_regime}  |  VIX: {vix}  |  Breadth: {breadth}  |  Credit: {credit}
OVERALL NEWS MOOD: {market_mood if market_mood else "Neutral/No Data"}
SENTIMENT TREND (Last 7 Days):
{chr(10).join([f"- {h['date']}: {h['mood']}" for h in mood_history]) if mood_history else "N/A"}

PRICE ACTION DIGEST:
{tech.get('daily_digest','')}
{tech.get('weekly_digest','')}

{history}
{port_stats}

NEWS:
{news_text if news_text else "No recent news found."}

SCORING GUIDE:
- Layer scores (-2 to +2 each), weighted by learned coefficients, regime multiplier applied.
- Final score ≥5 = Strong BUY, 3-4 = BUY, 0-2 = HOLD, ≤-1 = AVOID.
- If OBV divergence or RSI divergence present, reduce conviction by 20.
- If BB Squeeze active and score ≥3, raise conviction by 10 (breakout setup).
- Piotroski ≤3: Reduce conviction by 15 (weak balance sheet).
- Piotroski ≥7: Boost conviction by 10 (strong fundamentals quality).
- ROIC > 15%: Capital compounder — prioritise for long-term holds.
- Net insider buying: Boost conviction by 5. Heavy insider selling: Reduce by 10.
- Short interest > 15%: Flag elevated risk; consider smaller position sizing.
- NARROW breadth: market rally is concentrated — higher risk for small/mid caps.
- RISK_OFF credit: Bond market is de-risking — be cautious on new longs.
- Earnings within 5 days: downgrade any BUY to WATCH.
- Weekly misaligned: halve confidence on daily BUY signals.

RULES:
1. SELF-REFLECTION: Review your history. Adapt if previously wrong. Be brutally honest.
2. CHART PATTERNS: Use PRICE ACTION DIGEST. Call out Double Bottoms, Cup & Handle, Flags, H&S.
3. Use ATR stop provided — do NOT use 52W Low as stop. That is too wide for tactical entries.
4. Heavily weight Piotroski and ROIC for fundamental quality assessment.
5. If short interest > 20% and price > SMA50, flag as potential short squeeze setup.

RESPONSE FORMAT (EXACT):
RECOMMENDATION: [BUY/SELL/HOLD/WAIT/AVOID]
CONVICTION: [0-100]
ENTRY: $[price]
STOP_LOSS: $[price]
TARGET: $[price]
NEWS_SENTIMENT: [1-5]
REFLECTION: [1 sentence on what you learned from your history]

REASONS (top 3 strengths):
[reason]

RISKS (top 2 concerns):
[risk]

OUTLOOK (1-2 sentences):
[explanation]

---
Be precise, decisive, and tactical. Every word should help the trader act.
"""

    def _parse_recommendation(self, symbol: str, text: str, fund_score: int, 
                             tech_score: int, fund: Dict, tech: Dict, news: List[Dict] = None, save_dt: bool = True) -> Dict:
        """Parse Claude's response into structured format"""
        
        # Extract values from response
        lines = text.split("\n")
        
        rec_dict = {
            "symbol": symbol,
            "recommendation": "HOLD",
            "conviction": 50,
            "entry_price": tech.get("current_price", 0),
            "stop_loss": tech.get("low_52w", 0) * 0.95,
            "target_price": tech.get("high_52w", 0) * 1.1,
            "fundamentals_score": fund_score,
            "technical_score": tech_score,
            "reasoning": text,
            "reasons": [],
            "risks": [],
            "outlook": "",
            "similar_pattern": ""
        }
        
        # Robust parsing using RegEx
        for line in lines:
            if "RECOMMENDATION:" in line:
                rec_dict["recommendation"] = line.split(":")[-1].strip().split()[0].upper().replace("*", "")
            elif "CONVICTION:" in line:
                match = re.search(r"CONVICTION:\s*(\d+)", line)
                if match: rec_dict["conviction"] = int(match.group(1))
            elif "ENTRY:" in line:
                match = re.search(r"ENTRY:\s*\$?([\d,.]+)", line)
                if match: rec_dict["entry_price"] = float(match.group(1).replace(",", ""))
            elif "STOP_LOSS:" in line:
                match = re.search(r"STOP_LOSS:\s*\$?([\d,.]+)", line)
                if match: rec_dict["stop_loss"] = float(match.group(1).replace(",", ""))
            elif "TARGET:" in line:
                match = re.search(r"TARGET:\s*\$?([\d,.]+)", line)
                if match: rec_dict["target_price"] = float(match.group(1).replace(",", ""))
            elif "NEWS_SENTIMENT:" in line:
                match = re.search(r"NEWS_SENTIMENT:\s*(\d+)", line)
                if match: rec_dict["news_sentiment"] = int(match.group(1))
            elif "REFLECTION:" in line:
                rec_dict["reflection"] = line.split("REFLECTION:")[1].strip()
        
        # Store simplified news JSON for the UI
        if news:
            simplified_news = []
            for n in news[:3]:
                simplified_news.append({
                    "title": n['content'].get('title', 'No Title'),
                    "link": n['content'].get('canonicalUrl', {}).get('url', '#')
                })
            rec_dict["news_json"] = json.dumps(simplified_news)
        else:
            rec_dict["news_json"] = "[]"
        
        # Save to DB
        if save_dt:
            self.db.save_recommendation(rec_dict)
        
        return rec_dict
    
    def batch_analyze(self, symbols: List[str], market_mood: Optional[str] = None, 
                     mood_history: Optional[List[Dict]] = None) -> List[Dict]:
        """Analyze multiple stocks"""
        results = []
        for symbol in symbols:
            print(f"Analyzing {symbol}...")
            rec = self.analyze_stock(symbol, market_mood=market_mood, mood_history=mood_history)
            if rec:
                results.append(rec)
        return results
    
    def format_for_client(self, rec: Dict) -> str:
        """Format recommendation for client email"""
        
        return f"""
{'─'*60}
{rec['symbol']}: {rec['recommendation']} (Conviction {rec['conviction']}%)
{'─'*60}

ENTRY POINT: ${rec['entry_price']:.2f}
STOP LOSS:   ${rec['stop_loss']:.2f}
TARGET:      ${rec['target_price']:.2f}

Conviction {rec['conviction']}% means we're {rec['conviction']}% confident this works.

FUNDAMENTALS SCORE: {rec['fundamentals_score']}/13
TECHNICAL SCORE:    {rec['technical_score']}/5

WHY:
{rec['reasoning']}

RISKS:
{' | '.join(rec.get('risks', ['None identified']))}

{'─'*60}
"""


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    engine = RecommendationEngine()
    
    # Test on 5 large caps
    test_stocks = ["AAPL", "MSFT", "NVDA", "GOOGL", "TSLA"]
    
    print("\nAnalyzing large cap stocks...\n")
    
    recommendations = engine.batch_analyze(test_stocks)
    
    # Print results
    for rec in recommendations:
        print(engine.format_for_client(rec))
    
    # Show accuracy
    accuracy = engine.db.get_accuracy()
    print("\nDATABASE STATS:")
    print(f"Total recommendations: {accuracy['total_recommendations']}")
    print(f"Profitable: {accuracy['profitable']}")
    print(f"Accuracy: {accuracy['accuracy_percent']}%")
    print(f"Average return: {accuracy['average_return_percent']}%")
