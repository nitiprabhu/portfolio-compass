import yfinance as yf
from database import RecommendationDB
from position_sizer import calculate_position_size
from datetime import datetime

class AutoTrader:
    def __init__(self, db: RecommendationDB):
        self.db = db

    def sync_portfolio_equity(self):
        """Update total equity based on current market prices of held positions."""
        state = self.db.get_fund_state()
        ledger = self.db.get_active_ledger()
        
        if not ledger:
            self.db.update_fund_state(state["cash_balance"], state["cash_balance"])
            return state["cash_balance"]

        symbols = [p["symbol"] for p in ledger]
        tickers = yf.Tickers(" ".join(symbols))
        
        market_value = 0
        for p in ledger:
            symbol = p["symbol"]
            try:
                # Use fast price fetch
                price = tickers.tickers[symbol].fast_info['lastPrice']
                market_value += p["shares"] * price
            except:
                # Fallback
                hist = tickers.tickers[symbol].history(period="1d")
                if not hist.empty:
                    price = hist["Close"].iloc[-1]
                    market_value += p["shares"] * price
        
        total_equity = state["cash_balance"] + market_value
        self.db.update_fund_state(state["cash_balance"], total_equity)
        return total_equity

    def process_new_recommendations(self):
        """Find 'Strong BUY' recommendations and execute paper trades if cash is available."""
        state = self.db.get_fund_state()
        cash = state["cash_balance"]
        total_equity = state["total_equity"]
        
        # Max % to allocate to a new position (e.g. 20% of account)
        max_pos_size = total_equity * 0.20
        
        # Get recent recommendations (last 24h)
        with self.db.get_connection() as conn:
            if self.db.is_postgres:
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
                cursor = conn.cursor()
            
            # Handle different date syntax for Postgres vs SQLite
            date_filter = "CURRENT_TIMESTAMP - INTERVAL '24 hours'" if self.db.is_postgres else "datetime('now', '-1 day')"
            
            cursor.execute(f"""
                SELECT symbol, recommendation, conviction, entry_price, atr14, technical_score
                FROM recommendations 
                WHERE (recommendation = 'BUY' OR recommendation = 'STRONG BUY')
                  AND created_at > ({date_filter})
                ORDER BY created_at DESC
            """)
            recs = cursor.fetchall()
            print(f"DEBUG: Found {len(recs)} potential BUY/STRONG BUY recommendations from last 24h.")

        ledger = self.db.get_active_ledger()
        held_symbols = [p["symbol"] for p in ledger]
        print(f"DEBUG: Currently holding {len(held_symbols)} symbols: {held_symbols}")

        for r in recs:
            symbol = r["symbol"]
            print(f"DEBUG: Processing {symbol}...")
            if symbol in held_symbols: continue # Already own it
            
            if cash < (total_equity * 0.05): # Less than 5% cash left
                print(f"Skipping {symbol}: Insufficient cash ({cash:.2f})")
                continue

            # Calculate position size
            try:
                # Fetch volatility data
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="3mo")
                if hist.empty: continue
                
                close = hist["Close"]
                vol = float(close.pct_change().std() * (252**0.5) * 100)
                atr14 = r.get("atr14") or 0
                if atr14 == 0:
                    import pandas as pd
                    high, low, current = hist["High"], hist["Low"], hist["Close"]
                    tr = pd.concat([high - low, (high - current.shift()).abs(), (low - current.shift()).abs()], axis=1).max(axis=1)
                    atr14 = float(tr.rolling(14).mean().iloc[-1])
                
                entry = r.get("entry_price") or close.iloc[-1]
                print(f"DEBUG: {symbol} - Entry: {entry}, ATR14: {atr14}, Vol: {vol:.2f}%")
                
                sizing = calculate_position_size(
                    account_value=total_equity,
                    entry_price=entry,
                    atr14=atr14,
                    annual_volatility=vol,
                    n_positions=5
                )
                
                shares = sizing["shares"]
                print(f"DEBUG: {symbol} Sizing - Result: {shares} shares")
                cost = shares * entry
                
                # Double check affordability
                if cost > cash:
                    shares = int(cash / entry)
                    cost = shares * entry
                
                if shares > 0:
                    self.db.execute_paper_trade(symbol, shares, entry, "BUY")
                    cash -= cost # Local update for immediate next trade
            except Exception as e:
                print(f"Error buying {symbol}: {e}")

    def manage_existing_positions(self):
        """Monitor held positions for 'SELL' signals or Stop/Target hits."""
        ledger = self.db.get_active_ledger()
        if not ledger: return

        for p in ledger:
            symbol = p["symbol"]
            try:
                # Get latest engine verdict (simulate fresh analysis)
                # For now, we look at the 'outcomes' status which is updated by update_outcomes.py
                with self.db.get_connection() as conn:
                    if self.db.is_postgres:
                        from psycopg2.extras import RealDictCursor
                        cursor = conn.cursor(cursor_factory=RealDictCursor)
                    else:
                        conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
                        cursor = conn.cursor()
                    
                    cursor.execute(f"SELECT status, current_price FROM outcomes WHERE symbol = %s ORDER BY check_date DESC LIMIT 1", (symbol,))
                    outcome = cursor.fetchone()
                    
                    if outcome:
                        status = outcome["status"]
                        curr_price = outcome["current_price"]
                        
                        if status in ["HIT_TARGET", "HIT_STOP", "SELL", "AVOID"]:
                            self.db.execute_paper_trade(symbol, p["shares"], curr_price, "SELL")
            except Exception as e:
                print(f"Error managing position {symbol}: {e}")

if __name__ == "__main__":
    from database import RecommendationDB
    db = RecommendationDB()
    trader = AutoTrader(db)
    print("🤖 Running Auto-Trader Sync...")
    equity = trader.sync_portfolio_equity()
    print(f"Current Total Equity: ${equity:,.2f}")
    trader.manage_existing_positions()
    trader.process_new_recommendations()
    trader.sync_portfolio_equity()
