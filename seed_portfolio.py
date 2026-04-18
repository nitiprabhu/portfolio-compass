import sqlite3
from datetime import datetime

HOLDINGS = [
    {"symbol": "AVGO", "entry": 161.91},
    {"symbol": "GOOGL", "entry": 171.58},
    {"symbol": "CPER", "entry": 36.22},
    {"symbol": "URA", "entry": 56.83},
    {"symbol": "VNT", "entry": 40.53},
    {"symbol": "CPNG", "entry": 29.25},
    {"symbol": "SMH", "entry": 364.65},
    {"symbol": "CNXT", "entry": 47.51},
    {"symbol": "ARKW", "entry": 138.41},
    {"symbol": "STEP", "entry": 53.53},
    {"symbol": "INTC", "entry": 65.95},
]

def seed():
    conn = sqlite3.connect("recommendations.db")
    cursor = conn.cursor()
    
    # 1. Clear existing
    print("Clearing old recommendations and outcomes...")
    cursor.execute("DELETE FROM outcomes")
    cursor.execute("DELETE FROM recommendations")
    
    # 2. Insert new holdings
    print(f"Seeding {len(HOLDINGS)} positions...")
    for h in HOLDINGS:
        # Create a BUY recommendation
        # Using placeholder scores and reasoning for manual holdings
        cursor.execute("""
            INSERT INTO recommendations 
            (symbol, recommendation, conviction, entry_price, target_price, stop_loss, 
             fundamentals_score, technical_score, reasoning, risks, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            h["symbol"], 
            "BUY", 
            85, 
            h["entry"], 
            round(h["entry"] * 1.5, 2), # Default target 50%
            round(h["entry"] * 0.8, 2), # Default stop 20%
            10, 
            4,
            "Manual Entry: Actual Portfolio Holding",
            '[]',
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        rec_id = cursor.lastrowid
        
        # Create an OPEN outcome
        cursor.execute("""
            INSERT INTO outcomes (recommendation_id, symbol, entry_price, status, current_price, peak_price)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (rec_id, h["symbol"], h["entry"], "OPEN", h["entry"], h["entry"]))
        
    conn.commit()
    conn.close()
    print("Portfolio seeded successfully!")

if __name__ == "__main__":
    seed()
