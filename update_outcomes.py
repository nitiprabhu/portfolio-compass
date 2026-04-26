import os
import json
import yfinance as yf
from datetime import datetime, timedelta
from database import RecommendationDB

def update_all_outcomes():
    """
    Enhanced outcome updater with:
    - MAE (Max Adverse Excursion) / MFE (Max Favorable Excursion) tracking
    - Trailing ATR stop ratchet (never lowered, only raised)
    - Days held calculation
    - Tech layer snapshot preservation
    """
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
            
        cursor.execute("""
            SELECT id, symbol, recommendation, entry_price, target_price, stop_loss, created_at, atr14, tech_layer_snapshot
            FROM recommendations
        """)
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
                # Fetch recent history for MAE/MFE calculation
                history = tickers.tickers[symbol].history(period="5d")
                if history.empty: continue
                curr_price = history["Close"].iloc[-1]
                
                # Get high/low from recent history for MAE/MFE
                recent_high = float(history["High"].max())
                recent_low = float(history["Low"].min())
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
                continue
                
            action = r['recommendation']
            entry = r['entry_price']
            target = r['target_price']
            stop = r['stop_loss']
            atr14 = r.get('atr14') or 0
            
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
            
            # Calculate days held
            try:
                created = r['created_at']
                if isinstance(created, str):
                    created = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
                days_held = (datetime.now() - created).days
            except:
                days_held = 0

            # Update outcomes table
            # Check if exists
            cursor.execute(f"SELECT id, peak_price, max_adverse_excursion, max_favorable_excursion, trailing_stop FROM outcomes WHERE recommendation_id = {p}", (r['id'],))
            row = cursor.fetchone()
            
            now = datetime.now()
            
            if row:
                outcome_id = row['id']
                old_peak = row.get('peak_price') or 0
                old_mae = row.get('max_adverse_excursion') or 0
                old_mfe = row.get('max_favorable_excursion') or 0
                old_trailing_stop = row.get('trailing_stop') or (stop or 0)
                
                # Update peak price
                peak = max(old_peak, curr_price, recent_high)
                
                # ── MAE: Max Adverse Excursion (worst drawdown from entry) ──
                if entry and entry > 0 and action == 'BUY':
                    current_mae = ((entry - recent_low) / entry) * 100  # % below entry
                    mae = max(old_mae, current_mae)
                else:
                    mae = old_mae

                # ── MFE: Max Favorable Excursion (best gain from entry) ──
                if entry and entry > 0 and action == 'BUY':
                    current_mfe = ((recent_high - entry) / entry) * 100  # % above entry
                    mfe = max(old_mfe, current_mfe)
                else:
                    mfe = old_mfe

                # ── Trailing ATR Stop: ratchet up, never lower ──
                trailing_stop = old_trailing_stop
                if atr14 > 0 and action == 'BUY' and peak > 0:
                    new_trailing_stop = round(peak - 2.0 * atr14, 2)
                    if new_trailing_stop > old_trailing_stop:
                        trailing_stop = new_trailing_stop

                # Check trailing stop hit
                if action == 'BUY' and trailing_stop > 0 and curr_price <= trailing_stop and status == "OPEN":
                    status = "HIT_STOP"
                
                cursor.execute(f"""
                    UPDATE outcomes 
                    SET current_price = {p}, check_date = {p}, status = {p}, return_pct = {p}, 
                        peak_price = {p}, max_adverse_excursion = {p}, max_favorable_excursion = {p},
                        days_held = {p}, trailing_stop = {p}
                    WHERE id = {p}
                """, (curr_price, now, status, ret_pct, peak, mae, mfe, days_held, trailing_stop, outcome_id))
            else:
                # First time: calculate initial MAE/MFE
                initial_mae = 0
                initial_mfe = 0
                initial_trailing_stop = stop or 0

                if entry and entry > 0 and action == 'BUY':
                    initial_mae = max(0, ((entry - recent_low) / entry) * 100)
                    initial_mfe = max(0, ((recent_high - entry) / entry) * 100)
                    if atr14 > 0:
                        initial_trailing_stop = max(stop or 0, round(curr_price - 2.0 * atr14, 2))

                # Pull tech_layer_snapshot from recommendation
                snapshot = r.get('tech_layer_snapshot')
                if isinstance(snapshot, str):
                    pass  # Already JSON string
                elif isinstance(snapshot, dict):
                    snapshot = json.dumps(snapshot)
                else:
                    snapshot = None

                cursor.execute(f"""
                    INSERT INTO outcomes (recommendation_id, symbol, entry_price, entry_date, current_price, check_date, 
                                          status, return_pct, peak_price, max_adverse_excursion, max_favorable_excursion,
                                          days_held, trailing_stop, tech_layer_snapshot)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                """, (r['id'], symbol, entry, r['created_at'], curr_price, now, status, ret_pct, curr_price,
                      initial_mae, initial_mfe, days_held, initial_trailing_stop, snapshot))

        if not db.is_postgres:
            conn.commit()
            
    print("✅ Outcomes updated with MAE/MFE + trailing ATR stops.")

    # ── Auto-train calibrator if enough data ──────────────────────────────
    try:
        from signal_calibrator import SignalCalibrator
        calibrator = SignalCalibrator(db)
        result = calibrator.train()
        if result.get("status") == "trained":
            print(f"🧠 Calibrator retrained: weights updated (n={result['n_samples']}, acc={result['accuracy']:.1%})")
            if result.get("diagnostics"):
                d = result["diagnostics"]
                print(f"   Stop quality: {d.get('stop_quality', 'N/A')} (MFE/MAE ratio: {d.get('mfe_mae_ratio', 'N/A')})")
        else:
            print(f"🧠 Calibrator: {result.get('message', result.get('status'))}")
    except Exception as e:
        print(f"⚠️ Calibrator training skipped: {e}")

if __name__ == "__main__":
    update_all_outcomes()
