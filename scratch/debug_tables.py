
import os
import json
from database import RecommendationDB

# Manual .env load just for this script
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                os.environ[k] = v

def debug_db():
    db = RecommendationDB()
    print(f"Is Postgres: {db.is_postgres}")
    print(f"Has DATABASE_URL: {db.database_url is not None}")
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = [t[0] for t in cursor.fetchall()]
        print(f"Tables found: {tables}")
        
        if "news_intelligence" in tables:
            cursor.execute("SELECT COUNT(*) FROM news_intelligence")
            count = cursor.fetchone()[0]
            print(f"news_intelligence row count: {count}")

if __name__ == "__main__":
    debug_db()
