import os
import json
import yfinance as yf
from datetime import datetime, timedelta
from database import RecommendationDB

def update_all_outcomes():
    db = RecommendationDB()
    p = db._get_placeholder()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get all recommendations
        if db.is_postgres:
            from psycopg2.extras import RealDictCursor
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
            cursor = conn.cursor()
            
        cursor.execute("SELECT id, symbol, recommendation, entry_price, target_price, stop_loss, created_at FROM recommendations")
        recs = cursor.fetchall()
        
        if not recs:
            print("No recommendations found to update.")
            return
            
        symbols = list(set([r['symbol'] for r in recs]))
        print(f"Updating outcomes for {len(recs)} recommendations on {len(symbols)} symbols...")
        
        # Batch fetch prices
        tickers = yf.Tickers(" ".join(symbols))
        
        for r in recs:
            symbol = r['symbol']
            try:
                # Try to get live price, fallback to entry if unavailable
                history = tickers.tickers[symbol].history(period="1d")
                if history.empty: continue
                curr_price = history["Close"].iloc[-1]
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
                continue
                
            action = r['recommendation']
            entry = r['entry_price']
            target = r['target_price']
            stop = r['stop_loss']
            
            ret_pct = 0
            if entry and entry > 0:
                if action == 'BUY':
                    ret_pct = ((curr_price - entry) / entry) * 100
                elif action == 'SELL':
                    ret_pct = ((entry - curr_price) / entry) * 100
                    
            status = "OPEN"
            if action == 'BUY':
                if target and curr_price >= target: status = "HIT_TARGET"
                elif stop and curr_price <= stop: status = "HIT_STOP"
            elif action == 'SELL':
                if target and curr_price <= target: status = "HIT_TARGET"
                elif stop and curr_price >= stop: status = "HIT_STOP"
            
            # Update outcomes table
            # Check if exists
            cursor.execute(f"SELECT id, peak_price FROM outcomes WHERE recommendation_id = {p}", (r['id'],))
            row = cursor.fetchone()
            
            now = datetime.now()
            
            if row:
                outcome_id = row['id'] if db.is_postgres else row[0]
                old_peak = row['peak_price'] if db.is_postgres else row[1]
                peak = max(old_peak or 0, curr_price)
                
                cursor.execute(f"""
                    UPDATE outcomes 
                    SET current_price = {p}, check_date = {p}, status = {p}, return_pct = {p}, peak_price = {p}
                    WHERE id = {p}
                """, (curr_price, now, status, ret_pct, peak, outcome_id))
            else:
                cursor.execute(f"""
                    INSERT INTO outcomes (recommendation_id, symbol, entry_price, entry_date, current_price, check_date, status, return_pct, peak_price)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                """, (r['id'], symbol, entry, r['created_at'], curr_price, now, status, ret_pct, curr_price))

        if not db.is_postgres:
            conn.commit()
            
    print("Outcomes successfully updated via RecommendationDB.")

if __name__ == "__main__":
    update_all_outcomes()
