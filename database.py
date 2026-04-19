import os
import sqlite3
import json
from typing import Optional, List, Dict

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
                    reflection TEXT
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
                    peak_price REAL
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
            cursor.execute(f"""
                INSERT INTO recommendations 
                (symbol, recommendation, conviction, entry_price, stop_loss, 
                 target_price, fundamentals_score, technical_score, reasoning, risks_json, news_sentiment, news_json, atr_stop, atr14, reflection)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
                {"RETURNING id" if self.is_postgres else ""}
            """, (
                rec["symbol"], rec["recommendation"], rec["conviction"], rec["entry_price"],
                rec["stop_loss"], rec["target_price"], rec["fundamentals_score"],
                rec["technical_score"], rec["reasoning"], json.dumps(rec.get("risks", [])),
                rec.get("news_sentiment", 3), rec.get("news_json", "[]"),
                rec.get("atr_stop"), rec.get("atr14"), rec.get("reflection", "")
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
                results.append({
                    "id": row["id"] if not self.is_postgres else row["id"],
                    "run_date": row["run_date"],
                    "symbols": row["symbols"],
                    "aggregate_stats": json.loads(row["aggregate_stats"] if row["aggregate_stats"] else "{}")
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
                return {
                    "id": row["id"], "run_date": row["run_date"], "symbols": row["symbols"],
                    "aggregate_stats": json.loads(row["aggregate_stats"] if row["aggregate_stats"] else "{}"),
                    "results_json": json.loads(row["results_json"] if row["results_json"] else "{}")
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
