
import os
import sqlite3
import json
from database import RecommendationDB

def check_news():
    db = RecommendationDB()
    latest = db.get_latest_news_intelligence()
    if latest:
        print(f"Latest news intel found! ID: {latest['id']}")
        print(f"Run date: {latest['run_date']}")
        print(f"Data keys: {latest['data'].keys()}")
    else:
        print("No news intelligence found in database!")

if __name__ == "__main__":
    check_news()
