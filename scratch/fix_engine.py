import os

filepath = '/Users/nithish-prabhu/Downloads/trading/recommendation_engine.py'
with open(filepath, 'r') as f:
    lines = f.readlines()

# The init_db starts around line 15
# The conflicts were between 109 and 152
# But I already deleted them with sed 109,152d

new_code = """
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
            
            conn.commit()
    
    def log_api_usage(self, model: str, input_tokens: int, output_tokens: int, cost: float):
        \"\"\"Log API usage for cost tracking\"\"\"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(\"\"\"
                INSERT INTO api_usage (model, input_tokens, output_tokens, cost)
                VALUES (?, ?, ?, ?)
            \"\"\", (model, input_tokens, output_tokens, cost))
"""

# Find where watchlist ends
target_line = -1
for i, line in enumerate(lines):
    if 'expires_at TIMESTAMP' in line:
        target_line = i + 3 # Should be after the ) and """) and maybe a blank line
        break

if target_line != -1:
    lines.insert(target_line, new_code)
    with open(filepath, 'w') as f:
        f.writelines(lines)
    print(f"Successfully patched {filepath}")
else:
    print("Could not find target line")
