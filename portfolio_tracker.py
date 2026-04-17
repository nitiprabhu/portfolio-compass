import sqlite3
import yfinance as yf
from datetime import datetime
import pandas as pd

def track_portfolio():
    print(f"--- DAILY PORTFOLIO TRACKER ({datetime.now().strftime('%Y-%m-%d')}) ---")
    
    conn = sqlite3.connect("recommendations.db")
    # Fetch only the latest BUY recommendations for each symbol to avoid duplicate entries
    # Or just fetch everything in the 'outcomes' table that was a BUY and is currently OPEN
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.symbol, r.recommendation, r.entry_price, r.target_price, r.stop_loss, r.created_at, o.status
        FROM recommendations r
        LEFT JOIN outcomes o ON r.id = o.recommendation_id
        WHERE r.recommendation = 'BUY' AND (o.status IS NULL OR o.status = 'OPEN')
        GROUP BY r.symbol
        ORDER BY r.created_at DESC
    """)
    positions = cursor.fetchall()
    
    if not positions:
        print("No active open BUY positions found in the portfolio.")
        return
        
    symbols = [p[0] for p in positions]
    print(f"Tracking {len(symbols)} Active Holdings: {', '.join(symbols)}\n")
    
    # Fetch live data
    tickers = yf.Tickers(" ".join(symbols))
    
    total_invested = 0
    total_current = 0
    
    print(f"{'SYMBOL':<8} | {'ENTRY':<10} | {'LIVE PRICE':<10} | {'% RETURN':<10} | {'TARGET':<10} | {'STOP':<10} | {'STATUS'}")
    print("-" * 80)
    
    for pos in positions:
        symbol, action, entry, target, stop, date, status = pos
        if not entry: continue
        
        try:
            live_price = tickers.tickers[symbol].history(period="1d")["Close"].iloc[-1]
        except:
            live_price = entry # Fallback
            
        pnl_pct = ((live_price - entry) / entry) * 100
        
        # Position sizing (assuming $10,000 invested per stock for tracking purposes)
        shares = 10000 / entry
        total_invested += 10000
        total_current += (shares * live_price)
        
        alert = "✅ ON TRACK"
        if live_price >= target:
            alert = "🚀 HIT TARGET (SELL)"
        elif live_price <= stop:
            alert = "🛑 HIT STOP (SELL)"
        elif pnl_pct < -5:
            alert = "⚠️ UNDERPERFORMING"
            
        print(f"{symbol:<8} | ${entry:<9.2f} | ${live_price:<9.2f} | {pnl_pct:>+8.2f}% | ${target:<9.2f} | ${stop:<9.2f} | {alert}")
        
    print("-" * 80)
    total_pnl = ((total_current - total_invested) / total_invested) * 100
    print(f"PORTFOLIO OVERALL: {total_pnl:>+.2f}%")
    print(f"Total Invested: ${total_invested:,.2f} | Total Value: ${total_current:,.2f}")

if __name__ == "__main__":
    track_portfolio()
