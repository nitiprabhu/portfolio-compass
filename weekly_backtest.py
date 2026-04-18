import os
import sqlite3
import pandas as pd
import yfinance as yf
import json
import time
from datetime import datetime, timedelta
from recommendation_engine import RecommendationEngine

class WeeklyBacktestEngine(RecommendationEngine):
    def __init__(self):
        super().__init__()
        self.current_date = None
        
    def set_date(self, date_str):
        self.current_date = date_str

    def _get_technicals(self, symbol: str, sector: str = "Unknown", **kwargs) -> dict:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start="2024-01-01", end=self.current_date)
            
            if hist.empty:
                return {"error": f"No data for {symbol}"}
            
            current = hist["Close"].iloc[-1]
            sma50 = hist["Close"].tail(50).mean()
            sma200 = hist["Close"].tail(200).mean() if len(hist) >= 200 else None
            
            high52 = hist["Close"].tail(252).max() if len(hist) >= 252 else hist["Close"].max()
            low52 = hist["Close"].tail(252).min() if len(hist) >= 252 else hist["Close"].min()
            
            volatility = hist["Close"].pct_change().std() * (252 ** 0.5) * 100
            
            change_1y = ((current - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100) if len(hist) > 0 else 0
            
            # Short-term Price Action Digest (20 Days)
            daily_20 = hist.tail(20)
            daily_digest = "DAILY OHLC (Last 20 Days):\n"
            for d, row in daily_20.iterrows():
                daily_digest += f"{d.strftime('%Y-%m-%d')}: O:{row['Open']:.2f} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f}\n"

            # Macro Price Action Digest (26 Weeks)
            # Fetch longer history for weekly resampling
            weekly_hist = ticker.history(start="2023-01-01", end=self.current_date)
            weekly_26 = weekly_hist.resample('W-FRI').last().dropna().tail(26)
            weekly_digest = "WEEKLY OHLC (Last 26 Weeks):\n"
            for d, row in weekly_26.iterrows():
                weekly_digest += f"{d.strftime('%Y-%m-%d')}: O:{row['Open']:.2f} H:{row['High']:.2f} L:{row['Low']:.2f} C:{row['Close']:.2f}\n"

            return {
                "symbol": symbol,
                "current_price": current,
                "sma_50": sma50,
                "sma_200": sma200,
                "high_52w": high52,
                "low_52w": low52,
                "volatility": volatility,
                "change_1y": change_1y,
                "above_sma50": current > sma50,
                "above_sma200": current > sma200 if sma200 else False,
                "daily_digest": daily_digest,
                "weekly_digest": weekly_digest
            }
        except Exception as e:
            return {"error": str(e)}

    def batch_analyze(self, symbols: list) -> dict:
        """Run 90-day weekly backtest for a batch of symbols"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        results = {}
        
        for symbol in symbols:
            print(f"--- RUNNING BACKTEST: {symbol} ---")
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date.strftime('%Y-%m-%d'), end=end_date.strftime('%Y-%m-%d'))
                
                if hist.empty:
                    continue
                    
                weekly_dates = hist.resample('W-FRI').last().dropna().index.strftime('%Y-%m-%d').tolist()
                
                symbol_trades = []
                for i, date_str in enumerate(weekly_dates):
                    print(f"  [{symbol}] Progress: {i+1}/{len(weekly_dates)} (Analyzing week of {date_str})...")
                    self.set_date(date_str)
                    rec = self.analyze_stock(symbol, bypass_cache=True, save_to_db=False)
                    
                    if not rec:
                        print(f"  [{symbol}] Warning: No recommendation returned for {date_str}")
                        continue
                        
                    symbol_trades.append({
                        "date": date_str,
                        "action": rec.get("recommendation"),
                        "price": rec.get("entry_price"),
                        "conviction": rec.get("conviction"),
                        "score": f"{rec.get('fundamentals_score')}/{rec.get('technical_score')}",
                        "reasoning": rec.get("reasoning", "")
                    })
                    time.sleep(0.5)
                
                # Path-dependent 90-day trajectory valuation
                shares_owned = 0
                realized_cash = 0
                total_invested = 0
                
                try:
                    current_price = yf.Ticker(symbol).history(period="1d")["Close"].iloc[-1]
                except:
                    current_price = symbol_trades[-1]["price"] if symbol_trades else 0
                    
                for t in symbol_trades:
                    act = t["action"]
                    prc = t["price"]
                    
                    if act in ["BUY", "STRONG BUY"] and prc > 0:
                        shares_owned += (100.0 / prc)
                        total_invested += 100.0
                    elif act in ["SELL", "AVOID"] and shares_owned > 0:
                        realized_cash += (shares_owned * prc)
                        shares_owned = 0
                
                final_value = realized_cash + (shares_owned * current_price)
                pnl = 0
                if total_invested > 0:
                    pnl = ((final_value - total_invested) / total_invested) * 100
                
                results[symbol] = {
                    "trades": symbol_trades,
                    "current_price": current_price,
                    "pnl_if_followed": pnl,
                    "total_invested": total_invested,
                    "final_value": final_value,
                    "status": "Completed"
                }
            except Exception as e:
                results[symbol] = {"status": "Error", "error": str(e), "pnl_if_followed": 0, "total_invested": 0, "final_value": 0}
                
        return results

def run_backtest_job(symbols: list):
    engine = WeeklyBacktestEngine()
    results = engine.batch_analyze(symbols)
    
    # Calculate Aggregate Statistics
    total_inv = sum(res.get("total_invested", 0) for res in results.values())
    total_val = sum(res.get("final_value", 0) for res in results.values())
    overall_pnl = ((total_val - total_inv) / total_inv * 100) if total_inv > 0 else 0
    
    wins = sum(1 for res in results.values() if res.get("pnl_if_followed", 0) > 0)
    completed_count = sum(1 for res in results.values() if res.get("status") == "Completed")
    accuracy = (wins / completed_count * 100) if completed_count > 0 else 0
    
    aggregate_stats = {
        "total_invested": total_inv,
        "total_final_value": total_val,
        "overall_pnl_pct": overall_pnl,
        "win_rate": accuracy
    }
    
    # Save the full structured history to DB
    run_id = engine.db.save_backtest(symbols, aggregate_stats, results)
    
    # For UI progress reset, delete the lock file
    if os.path.exists("backtest_results.json"):
        os.remove("backtest_results.json")
        
    print(f"Backtest Job {run_id} Completed.")

if __name__ == "__main__":
    symbols = ["AAPL", "GOOGL"]
    run_backtest_job(symbols)

