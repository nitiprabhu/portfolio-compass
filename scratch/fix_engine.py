import os

filepath = '/Users/nithish-prabhu/Downloads/trading/recommendation_engine.py'
with open(filepath, 'r') as f:
    lines = f.readlines()

# Totally clean start for the class methods
# Find where the class starts
header = []
for line in lines:
    header.append(line)
    if 'class RecommendationDB:' in line:
        break

rest_of_file = []
start_collecting = False
for line in lines:
    if 'def save_recommendation' in line:
        start_collecting = True
    if start_collecting:
        rest_of_file.append(line)

new_class_methods = """
    def __init__(self, db_path: str = \"recommendations.db\"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                    risks_json TEXT,
                    outlook TEXT,
                    news_sentiment REAL,
                    news_json TEXT,
                    atr_stop REAL,
                    atr14 REAL
                )
            \"\"\")
            
            conn.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS outcomes (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT,
                    status TEXT, -- OPEN, CLOSED
                    entry_price REAL,
                    current_price REAL,
                    return_pct REAL,
                    trailing_stop REAL,
                    check_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            \"\"\")
            
            conn.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS backtests (
                    id INTEGER PRIMARY KEY,
                    run_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    symbols TEXT,
                    aggregate_stats JSON,
                    results_json JSON
                )
            \"\"\")
            
            conn.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS api_usage (
                    id INTEGER PRIMARY KEY,
                    model TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cost REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            \"\"\")

            conn.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL UNIQUE,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            \"\"\")

            conn.execute(\"\"\"
                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    quantity REAL,
                    entry_price REAL,
                    current_price REAL,
                    total_investment REAL,
                    current_value REAL,
                    status TEXT DEFAULT 'OPEN', -- OPEN, CLOSED
                    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at TIMESTAMP
                )
            \"\"\")
            
            conn.commit()

    def log_api_usage(self, model: str, input_tokens: int, output_tokens: int, cost: float):
        \"\"\"Log API usage for cost tracking\"\"\"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(\"\"\"
                INSERT INTO api_usage (model, input_tokens, output_tokens, cost)
                VALUES (?, ?, ?, ?)
            \"\"\", (model, input_tokens, output_tokens, cost))

"""

with open(filepath, 'w') as f:
    f.writelines(header)
    f.write(new_class_methods)
    f.writelines(rest_of_file)

print("Successfully reconstructed RecommendationDB with proper indentation.")
