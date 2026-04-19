import os
import json
import sqlite3
import pandas as pd
import yfinance as yf
from recommendation_engine import RecommendationEngine

class DailyBacktestEngine(RecommendationEngine):
    def __init__(self):
        super().__init__()
        self.current_date = None
        
    def set_date(self, date_str):
        self.current_date = date_str

    def _get_technicals(self, symbol: str, sector: str = "Unknown", **kwargs) -> dict:
        try:
            ticker = yf.Ticker(symbol)
            # Fetch data up to the simulated current date
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
            return {"error": str(e)}

if __name__ == "__main__":
    symbol = "NVDA"
    start_date = "2026-01-01"
    end_date = "2026-04-18"
    
    print(f"--- DAILY BACKTEST: {symbol} ---")
    print(f"Period: {start_date} to {end_date}")
    
    # Get all trading days in this period
    ticker = yf.Ticker(symbol)
    hist = ticker.history(start=start_date, end=end_date)
    trading_dates = hist.index.strftime('%Y-%m-%d').tolist()
    
    if not trading_dates:
        print("No trading data found for this period.")
        exit(0)
        
    engine = DailyBacktestEngine()
    
    last_rec = None
    last_action = None
    trades = []
    
    import time
    
    print("Running analysis... This will only output when the signal changes.")
    print("-" * 60)
    
    for date_str in trading_dates:
        engine.set_date(date_str)
        rec = engine.analyze_stock(symbol)
        
        if not rec:
            continue
            
        current_action = rec.get("recommendation")
        price = rec.get("entry_price")
        
        if current_action != last_action:
            print(f"[{date_str}] Signal Changed -> {current_action}")
            print(f"   Price: ${price:.2f} | Conviction: {rec.get('conviction')}%")
            print(f"   Scores -> Fund: {rec.get('fundamentals_score')}/13 | Tech: {rec.get('technical_score')}/5")
            print(f"   Why: {rec.get('reasoning').split('REASONS')[0].strip()[-100:]}")
            print("-" * 60)
            
            trades.append({
                "date": date_str,
                "action": current_action,
                "price": price
            })
            
            last_action = current_action
            
        # Sleep slightly to avoid overwhelming rate limits
        time.sleep(0.5)
        
    print("\n--- SUMMARY OF SIGNALS ---")
    current_price = hist["Close"].iloc[-1]
    print(f"Current Price (Apr 18): ${current_price:.2f}")
    if trades:
        print(f"Total signal changes: {len(trades)}")
        # Simple simulated PnL if we bought on first BUY
        first_buy = next((t for t in trades if t["action"] == "BUY"), None)
        if first_buy:
            pnl = ((current_price - first_buy["price"]) / first_buy["price"]) * 100
            print(f"If bought on first BUY signal ({first_buy['date']} at ${first_buy['price']:.2f}): {pnl:.2f}% return.")
