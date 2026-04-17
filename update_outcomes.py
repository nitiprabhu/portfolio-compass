import sqlite3
import yfinance as yf
from datetime import datetime

def update_outcomes():
    db_path = "recommendations.db"
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all recommendations that haven't hit a final state
    cursor.execute("""
        SELECT id, symbol, recommendation, entry_price, target_price, stop_loss, created_at
        FROM recommendations
    """)
    recs = cursor.fetchall()
    
    symbols_to_fetch = set([r[1] for r in recs])
    
    if not symbols_to_fetch:
        print("No recommendations to track.")
        return
        
    print(f"Tracking outcomes for {len(recs)} total recommendations on {len(symbols_to_fetch)} symbols...")
    
    # Batch fetch current prices
    ticker_data = yf.Tickers(" ".join(symbols_to_fetch))
    
    for r in recs:
        rec_id, symbol, action, entry, target, stop, created_at = r
        
        try:
            curr_price = ticker_data.tickers[symbol].history(period="1d")["Close"].iloc[-1]
        except:
            continue
            
        ret_pct = 0
        if entry and entry > 0:
            if action == 'BUY':
                ret_pct = ((curr_price - entry) / entry) * 100
            elif action == 'SELL':
                ret_pct = ((entry - curr_price) / entry) * 100
                
        status = "OPEN"
        if action == 'BUY':
            if target and curr_price >= target:
                status = "HIT_TARGET"
            elif stop and curr_price <= stop:
                status = "HIT_STOP"
        elif action == 'SELL':
            if target and curr_price <= target:
                status = "HIT_TARGET"
            elif stop and curr_price >= stop:
                status = "HIT_STOP"
                
        # Insert or replace outcome
        # Since we might be updating an existing outcome, check if exists
        cursor.execute("SELECT id FROM outcomes WHERE recommendation_id = ?", (rec_id,))
        out_exists = cursor.fetchone()
        
        if out_exists:
            cursor.execute("""
                UPDATE outcomes 
                SET current_price = ?, check_date = ?, status = ?, return_pct = ?
                WHERE recommendation_id = ?
            """, (curr_price, datetime.now(), status, ret_pct, rec_id))
        else:
            cursor.execute("""
                INSERT INTO outcomes (recommendation_id, symbol, entry_price, entry_date, current_price, check_date, status, return_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (rec_id, symbol, entry, created_at, curr_price, datetime.now(), status, ret_pct))
            
    conn.commit()
    conn.close()
    print("Outcomes successfully updated! Dashboard Stats will now be populated.")

if __name__ == "__main__":
    update_outcomes()
