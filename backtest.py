import os
import json
import sqlite3
import yfinance as yf
from recommendation_engine import RecommendationEngine

class BacktestEngine(RecommendationEngine):
    def __init__(self, backtest_date="2026-01-15"):
        super().__init__()
        self.backtest_date = backtest_date
        
    def _get_technicals(self, symbol: str) -> dict:
        try:
            ticker = yf.Ticker(symbol)
            # Fetch data up to backtest_date
            hist = ticker.history(start="2024-01-01", end=self.backtest_date)
            
            if hist.empty:
                return {"error": f"No data for {symbol}"}
            
            current = hist["Close"].iloc[-1]
            sma50 = hist["Close"].tail(50).mean()
            sma200 = hist["Close"].tail(200).mean() if len(hist) >= 200 else None
            
            high52 = hist["Close"].tail(252).max() if len(hist) >= 252 else hist["Close"].max()
            low52 = hist["Close"].tail(252).min() if len(hist) >= 252 else hist["Close"].min()
            
            volatility = hist["Close"].pct_change().std() * (252 ** 0.5) * 100
            
            change_1y = ((current - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100) if len(hist) > 0 else 0
            
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
            }
        except Exception as e:
            return {"error": f"Could not fetch technicals for {symbol}: {e}"}

if __name__ == "__main__":
    symbols = ["SOXL"]
    engine = BacktestEngine(backtest_date="2026-01-31")
    
    print(f"--- RUNNING BACKTEST (Simulation Date: 2026-01-31) ---")
    
    for sym in symbols:
        print(f"\nAnalyzing {sym} as of Jan 2026...")
        rec = engine.analyze_stock(sym)
        if rec:
            print(f"Recommendation: {rec['recommendation']} | Conviction: {rec['conviction']}%")
            print(f"Entry Price (Jan): ${rec['entry_price']:.2f}")
            print(f"Target: ${rec['target_price']:.2f} | Stop Loss: ${rec['stop_loss']:.2f}")
            
            # Fetch actual current price to see if it worked
            actual_curr = yf.Ticker(sym).history(period="1d")["Close"].iloc[-1]
            print(f"--> ACTUAL Current Price (April 2026): ${actual_curr:.2f}")
            
            ret = ((actual_curr - rec['entry_price']) / rec['entry_price']) * 100
            
            status = "⏳ Open"
            if actual_curr >= rec['target_price']:
                status = "✅ Hit Target"
            elif actual_curr <= rec['stop_loss']:
                status = "❌ Hit Stop Loss"
                
            print(f"--> Return since Jan: {ret:.2f}% | Status: {status}")
            print("-" * 50)
