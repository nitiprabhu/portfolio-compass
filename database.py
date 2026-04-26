import os
import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict
from dotenv import load_dotenv

load_dotenv() # Load environment variables from .env

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

class RecommendationDB:
    def __init__(self, db_path: str = "recommendations.db"):
        self.db_path = db_path
        self.database_url = os.environ.get("DATABASE_URL")
        self.is_postgres = self.database_url is not None and self.database_url.startswith("postgres")
        print(f"📡 [DB INIT] Mode: {'PostgreSQL' if self.is_postgres else 'SQLite (Local)'}")
        self.init_db()

    def get_connection(self):
        if self.is_postgres:
            if not HAS_POSTGRES:
                raise ImportError("psycopg2-binary is required for PostgreSQL support.")
            conn = psycopg2.connect(self.database_url, sslmode='require')
            conn.autocommit = True
            return conn
        else:
            return sqlite3.connect(self.db_path)

    def _get_placeholder(self):
        return "%s" if self.is_postgres else "?"

    def init_db(self):
        pk_type = "SERIAL PRIMARY KEY" if self.is_postgres else "INTEGER PRIMARY KEY"
        json_type = "JSONB" if self.is_postgres else "TEXT"
        timestamp_default = "CURRENT_TIMESTAMP"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id {pk_type},
                    created_at TIMESTAMP DEFAULT {timestamp_default},
                    symbol TEXT,
                    recommendation TEXT,
                    conviction INTEGER,
                    entry_price REAL,
                    stop_loss REAL,
                    target_price REAL,
                    fundamentals_score INTEGER,
                    technical_score INTEGER,
                    reasoning TEXT,
                    reasons_json TEXT,
                    risks_json {json_type},
                    outlook TEXT,
                    news_sentiment REAL,
                    news_json TEXT,
                    atr_stop REAL,
                    atr14 REAL,
                    reflection TEXT,
                    tech_layer_snapshot {json_type}
                )
            """)
            
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS outcomes (
                    id {pk_type},
                    recommendation_id INTEGER,
                    symbol TEXT,
                    entry_price REAL,
                    entry_date TIMESTAMP DEFAULT {timestamp_default},
                    current_price REAL,
                    check_date TIMESTAMP DEFAULT {timestamp_default},
                    status TEXT,
                    return_pct REAL,
                    peak_price REAL,
                    max_adverse_excursion REAL,
                    max_favorable_excursion REAL,
                    days_held INTEGER,
                    tech_layer_snapshot {json_type},
                    trailing_stop REAL
                )
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS layer_weights (
                    id {pk_type},
                    trained_at TIMESTAMP DEFAULT {timestamp_default},
                    w_trend REAL DEFAULT 1.0,
                    w_momentum REAL DEFAULT 1.0,
                    w_volatility REAL DEFAULT 1.0,
                    w_volume REAL DEFAULT 1.0,
                    w_rs REAL DEFAULT 1.0,
                    w_guards REAL DEFAULT 1.0,
                    n_samples INTEGER,
                    accuracy REAL
                )
            """)
            
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS api_usage (
                    id {pk_type},
                    model TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cost REAL,
                    timestamp TIMESTAMP DEFAULT {timestamp_default}
                )
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id {pk_type},
                    symbol TEXT NOT NULL UNIQUE,
                    added_at TIMESTAMP DEFAULT {timestamp_default},
                    expires_at TIMESTAMP
                )
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS backtests (
                    id {pk_type},
                    run_date TIMESTAMP DEFAULT {timestamp_default},
                    symbols TEXT,
                    aggregate_stats {json_type},
                    results_json {json_type}
                )
            """)
            
            # Add news_intelligence table
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS news_intelligence (
                    id {pk_type},
                    run_date TIMESTAMP DEFAULT {timestamp_default},
                    data_json {json_type},
                    expires_at TIMESTAMP
                )
            """)
            
            # 10. Managed Fund: Ledger for active positions
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS portfolio_ledger (
                    id {pk_type},
                    symbol TEXT NOT NULL,
                    shares REAL NOT NULL,
                    avg_entry_price REAL NOT NULL,
                    total_cost REAL NOT NULL,
                    added_at TIMESTAMP DEFAULT {timestamp_default},
                    last_price REAL,
                    current_value REAL,
                    pnl_pct REAL
                )
            """)

            # 11. Managed Fund: State (Cash vs Equity)
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS fund_state (
                    id {pk_type},
                    cash_balance REAL DEFAULT 10000.0,
                    total_equity REAL DEFAULT 10000.0,
                    updated_at TIMESTAMP DEFAULT {timestamp_default}
                )
            """)
            
            # Initialise fund if empty
            cursor.execute("SELECT count(*) FROM fund_state")
            if cursor.fetchone()[0] == 0:
                cursor.execute(f"INSERT INTO fund_state (cash_balance, total_equity) VALUES (10000.0, 10000.0)")

            if not self.is_postgres:
                conn.commit()

    def log_api_usage(self, model: str, input_tokens: int, output_tokens: int, cost: float):
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"INSERT INTO api_usage (model, input_tokens, output_tokens, cost) VALUES ({p}, {p}, {p}, {p})", (model, input_tokens, output_tokens, cost))
            if not self.is_postgres: conn.commit()

    def save_recommendation(self, rec: Dict) -> int:
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Serialize tech_layer_snapshot if present
            snapshot_json = json.dumps(rec.get("tech_layer_snapshot")) if rec.get("tech_layer_snapshot") else None
            cursor.execute(f"""
                INSERT INTO recommendations 
                (symbol, recommendation, conviction, entry_price, stop_loss, 
                 target_price, fundamentals_score, technical_score, reasoning, risks_json, 
                 news_sentiment, news_json, atr_stop, atr14, reflection, tech_layer_snapshot)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                {"RETURNING id" if self.is_postgres else ""}
            """, (
                rec["symbol"], rec["recommendation"], rec["conviction"], rec["entry_price"],
                rec["stop_loss"], rec["target_price"], rec["fundamentals_score"],
                rec["technical_score"], rec["reasoning"], json.dumps(rec.get("risks", [])),
                rec.get("news_sentiment", 3), rec.get("news_json", "[]"),
                rec.get("atr_stop"), rec.get("atr14"), rec.get("reflection", ""),
                snapshot_json
            ))
            if self.is_postgres:
                return cursor.fetchone()[0]
            else:
                conn.commit()
                return cursor.lastrowid

    def get_accuracy(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM recommendations WHERE recommendation = 'BUY'")
            total_buys = cursor.fetchone()[0]
            cursor.execute("""
                SELECT COUNT(*) FROM recommendations r
                WHERE r.recommendation = 'BUY'
                AND EXISTS (SELECT 1 FROM outcomes o WHERE o.recommendation_id = r.id AND (o.status = 'HIT_TARGET' OR o.return_pct > 0))
            """)
            profitable_buys = cursor.fetchone()[0]
            cursor.execute("SELECT AVG(return_pct) FROM outcomes WHERE status IN ('HIT_TARGET', 'CLOSED_EARLY')")
            avg_return = cursor.fetchone()[0] or 0
            return {
                "total_recommendations": total_buys,
                "profitable": profitable_buys,
                "accuracy_percent": round((profitable_buys / total_buys * 100) if total_buys > 0 else 0, 1),
                "average_return_percent": round(avg_return, 2)
            }

    def save_backtest(self, symbols: list, aggregate_stats: dict, results: dict) -> int:
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO backtests (symbols, aggregate_stats, results_json) VALUES ({p}, {p}, {p})",
                (",".join(symbols), json.dumps(aggregate_stats), json.dumps(results))
            )
            if not self.is_postgres: conn.commit()
            return cursor.lastrowid if not self.is_postgres else None

    def get_recent_backtests(self) -> list:
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute("SELECT id, run_date, symbols, aggregate_stats FROM backtests ORDER BY run_date DESC LIMIT 10")
            results = []
            for row in cursor.fetchall():
                val = row["aggregate_stats"]
                results.append({
                    "id": row["id"],
                    "run_date": row["run_date"],
                    "symbols": row["symbols"],
                    "aggregate_stats": val if isinstance(val, dict) else json.loads(val or "{}")
                })
            return results

    def get_backtest_by_id(self, backtest_id: int) -> dict:
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute(f"SELECT * FROM backtests WHERE id = {p}", (backtest_id,))
            row = cursor.fetchone()
            if row:
                as_val = row["aggregate_stats"]
                rj_val = row["results_json"]
                return {
                    "id": row["id"], "run_date": row["run_date"], "symbols": row["symbols"],
                    "aggregate_stats": as_val if isinstance(as_val, dict) else json.loads(as_val or "{}"),
                    "results_json": rj_val if isinstance(rj_val, dict) else json.loads(rj_val or "{}")
                }
            return None

    def get_last_recommendation(self, symbol: str) -> Optional[Dict]:
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute(f"SELECT * FROM recommendations WHERE symbol = {p} ORDER BY created_at DESC LIMIT 1", (symbol,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_news_intelligence(self, data: dict, ttl_days: int = 7):
        import datetime
        p = self._get_placeholder()
        expires_at = (datetime.datetime.now() + datetime.timedelta(days=ttl_days)).strftime('%Y-%m-%d %H:%M:%S')
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO news_intelligence (data_json, expires_at) VALUES ({p}, {p})",
                (json.dumps(data), expires_at)
            )
            if not self.is_postgres: conn.commit()

    def get_latest_news_intelligence(self) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute("SELECT * FROM news_intelligence ORDER BY run_date DESC LIMIT 1")
            row = cursor.fetchone()
            print(f"📂 [DB NEWS] Row found: {row is not None}")
            if row:
                val = row["data_json"]
                return {
                    "id": row["id"],
                    "run_date": row["run_date"],
                    "data": val if isinstance(val, dict) else json.loads(val or "{}"),
                    "expires_at": row["expires_at"]
                }
            return None

    def save_discovery_results(self, data: list):
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT INTO discovery_results (data_json) VALUES ({p})",
                (json.dumps(data),)
            )
            if not self.is_postgres: conn.commit()

    def get_latest_discovery_results(self) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute("SELECT * FROM discovery_results ORDER BY run_date DESC LIMIT 1")
            row = cursor.fetchone()
            if row:
                val = row["data_json"]
                return {
                    "id": row["id"],
                    "run_date": row["run_date"],
                    "data": val if isinstance(val, list) else json.loads(val or "[]")
                }
            return None

    # ── Layer Weights (Feedback Loop) ──────────────────────────────────────

    def save_layer_weights(self, weights: Dict, n_samples: int, accuracy: float):
        """Persist learned layer weights from the signal calibrator."""
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                INSERT INTO layer_weights (w_trend, w_momentum, w_volatility, w_volume, w_rs, w_guards, n_samples, accuracy)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """, (
                weights.get("w_trend", 1.0), weights.get("w_momentum", 1.0),
                weights.get("w_volatility", 1.0), weights.get("w_volume", 1.0),
                weights.get("w_rs", 1.0), weights.get("w_guards", 1.0),
                n_samples, accuracy
            ))
            if not self.is_postgres: conn.commit()

    def get_latest_layer_weights(self) -> Optional[Dict]:
        """Load the most recently trained layer weights."""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute("SELECT * FROM layer_weights ORDER BY trained_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_calibration_data(self) -> List[Dict]:
        """Fetch closed outcomes with their tech layer snapshots for calibrator training."""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor) if self.is_postgres else conn.cursor()
            if not self.is_postgres: conn.row_factory = sqlite3.Row
            cursor.execute("""
                SELECT o.status, o.return_pct, o.tech_layer_snapshot, o.max_adverse_excursion, o.max_favorable_excursion
                FROM outcomes o
                WHERE o.status IN ('HIT_TARGET', 'HIT_STOP', 'CLOSED_EARLY')
                  AND o.tech_layer_snapshot IS NOT NULL
                ORDER BY o.check_date DESC
            """)
            results = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                snapshot = row_dict.get("tech_layer_snapshot")
                if snapshot:
                    if isinstance(snapshot, str):
                        snapshot = json.loads(snapshot)
                    row_dict["tech_layer_snapshot"] = snapshot
                    results.append(row_dict)
            return results

    def get_fund_state(self) -> Dict:
        """Get current cash and total equity from the fund state."""
        with self.get_connection() as conn:
            if self.is_postgres:
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
                cursor = conn.cursor()
            cursor.execute("SELECT cash_balance, total_equity FROM fund_state ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else {"cash_balance": 10000.0, "total_equity": 10000.0}

    def update_fund_state(self, cash: float, total_equity: float):
        """Update the fund state with new cash and equity values."""
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"INSERT INTO fund_state (cash_balance, total_equity) VALUES ({p}, {p})", (cash, total_equity))
            if not self.is_postgres: conn.commit()

    def get_active_ledger(self) -> List[Dict]:
        """Get all active positions from the ledger."""
        with self.get_connection() as conn:
            if self.is_postgres:
                from psycopg2.extras import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
                conn.row_factory = lambda cursor, row: dict(zip([col[0] for col in cursor.description], row))
                cursor = conn.cursor()
            cursor.execute("SELECT * FROM portfolio_ledger ORDER BY symbol ASC")
            return [dict(ix) for ix in cursor.fetchall()]

    def execute_paper_trade(self, symbol: str, shares: float, price: float, action: str):
        """Execute a buy/sell trade in the virtual fund ledger."""
        p = self._get_placeholder()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            state = self.get_fund_state()
            cash = float(state["cash_balance"])
            
            if action == "BUY":
                cost = shares * price
                if cost > cash * 1.05: # Slight margin for floating point
                     print(f"Insufficient cash for {symbol}: Need {cost}, Have {cash}")
                     return
                
                # Update cash
                new_cash = cash - cost
                
                # Add to ledger (if exists, update average; else insert)
                cursor.execute(f"SELECT id, shares, avg_entry_price, total_cost FROM portfolio_ledger WHERE symbol = {p}", (symbol,))
                row = cursor.fetchone()
                if row:
                    old_shares = row[1] if not isinstance(row, dict) else row["shares"]
                    old_cost = row[3] if not isinstance(row, dict) else row["total_cost"]
                    new_shares = old_shares + shares
                    new_cost = old_cost + cost
                    new_avg = new_cost / new_shares
                    cursor.execute(f"UPDATE portfolio_ledger SET shares={p}, avg_entry_price={p}, total_cost={p} WHERE symbol={p}", (new_shares, new_avg, new_cost, symbol))
                else:
                    cursor.execute(f"INSERT INTO portfolio_ledger (symbol, shares, avg_entry_price, total_cost) VALUES ({p}, {p}, {p}, {p})", (symbol, shares, price, cost))
                
                self.update_fund_state(new_cash, state["total_equity"])
                print(f"💰 [PAPER TRADE] BOUGHT {shares:.2f} {symbol} @ ${price:.2f}")

            elif action == "SELL":
                cursor.execute(f"SELECT id, shares, total_cost FROM portfolio_ledger WHERE symbol = {p}", (symbol,))
                row = cursor.fetchone()
                if not row: return
                
                held_shares = row[1] if not isinstance(row, dict) else row["shares"]
                shares_to_sell = min(shares, held_shares)
                proceeds = shares_to_sell * price
                
                # Update cash
                new_cash = cash + proceeds
                
                if held_shares <= shares_to_sell:
                    cursor.execute(f"DELETE FROM portfolio_ledger WHERE symbol = {p}", (symbol,))
                else:
                    new_remaining = held_shares - shares_to_sell
                    # Adjust cost basis proportionally
                    old_cost = row[2] if not isinstance(row, dict) else row["total_cost"]
                    new_cost = old_cost * (new_remaining / held_shares)
                    cursor.execute(f"UPDATE portfolio_ledger SET shares={p}, total_cost={p} WHERE symbol={p}", (new_remaining, new_cost, symbol))
                
                self.update_fund_state(new_cash, state["total_equity"])
                print(f"💰 [PAPER TRADE] SOLD {shares_to_sell:.2f} {symbol} @ ${price:.2f}")

            if not self.is_postgres: conn.commit()
