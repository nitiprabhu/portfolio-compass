from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import sqlite3
import yfinance as yf
import asyncio
from datetime import datetime, timedelta
import os
import httpx

from recommendation_engine import RecommendationEngine

app = FastAPI(title="Portfolio Compass API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = RecommendationEngine()

class AnalysisRequest(BaseModel):
    symbols: List[str]

@app.get("/api/recommendations")
def get_all_recommendations():
    try:
        with sqlite3.connect(engine.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 50")
            rows = cursor.fetchall()
            return {"status": "success", "data": [dict(ix) for ix in rows]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/analyze")
def trigger_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    def run_analysis(symbols):
        engine.batch_analyze(symbols)

    background_tasks.add_task(run_analysis, req.symbols)
    return {"status": "success", "message": f"Started background analysis for {len(req.symbols)} symbols."}

@app.get("/api/accuracy")
def get_accuracy_stats():
    try:
        stats = engine.db.get_accuracy()
        return {"status": "success", "data": stats}
    except Exception as e:
        return {"status": "error", "message": str(e)}
@app.get("/api/portfolio")
def get_portfolio():
    try:
        with sqlite3.connect(engine.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.symbol, r.recommendation, r.entry_price, r.target_price, r.stop_loss, r.created_at, o.status
                FROM recommendations r
                LEFT JOIN outcomes o ON r.id = o.recommendation_id
                WHERE r.recommendation = 'BUY' AND (o.status IS NULL OR o.status = 'OPEN')
                GROUP BY r.symbol
                ORDER BY r.created_at DESC
            """)
            positions = cursor.fetchall()

        if not positions:
            return {"status": "success", "data": [], "summary": {}}
            
        symbols = [p[0] for p in positions]
        tickers = yf.Tickers(" ".join(symbols))
        
        portfolio_data = []
        total_invested = 0
        total_current = 0
        
        for pos in positions:
            symbol, action, entry, target, stop, date, status = pos
            if not entry: continue
            
            try:
                live_price = tickers.tickers[symbol].history(period="1d")["Close"].iloc[-1]
            except:
                live_price = entry
                
            pnl_pct = ((live_price - entry) / entry) * 100
            shares = 10000 / entry
            total_invested += 10000
            total_current += (shares * live_price)
            
            alert = "ON TRACK"
            if live_price >= target: alert = "HIT TARGET"
            elif live_price <= stop: alert = "HIT STOP"
            elif pnl_pct < -5: alert = "UNDERPERFORMING"
                
            portfolio_data.append({
                "symbol": symbol,
                "entry": entry,
                "live_price": live_price,
                "pnl_pct": pnl_pct,
                "target": target,
                "stop": stop,
                "alert": alert
            })
            
        summary = {
            "total_pnl_pct": ((total_current - total_invested) / total_invested) * 100 if total_invested else 0,
            "total_invested": total_invested,
            "total_value": total_current
        }
            
        return {"status": "success", "data": portfolio_data, "summary": summary}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_telegram_alert(message: str):
    """Fires a message directly to your Telegram lock screen"""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Telegram keys missing. Skipping alert.")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        httpx.post(url, json=payload, timeout=10.0)
    except Exception as e:
        print(f"Telegram failed: {e}")

async def background_daily_analysis():
    """Runs automatically every day to keep the dashboard constantly updated without human interaction"""
    while True:
        current_day = datetime.now().weekday()
        if current_day < 5:
            symbols_to_track = ["AAPL", "NVDA", "MSFT", "SOXX", "SOXL", "ASTS", "RKLB", "IOT", "PLTR"]
            try:
                print(f"[{datetime.now()}] Executing Automated Daily Analysis Cron...")
                engine.batch_analyze(symbols_to_track)
                
                # Fetch fresh recommendations made in the last 15 minutes
                time_threshold = (datetime.now() - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
                with sqlite3.connect(engine.db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT symbol, recommendation, conviction, entry_price, target_price, stop_loss 
                        FROM recommendations 
                        WHERE created_at > ? AND recommendation = 'BUY'
                    """, (time_threshold,))
                    fresh_buys = cursor.fetchall()
                
                if fresh_buys:
                    alert_text = "🚨 <b>Portfolio Compass - New Signals</b> 🚨\n\n"
                    for b in fresh_buys:
                        sym, action, conv, entry, target, stop = b
                        alert_text += f"📈 <b>{sym}</b>: {action} ({conv}% Conviction)\n"
                        alert_text += f"💵 Entry: ${entry:.2f} | Tgt: ${target:.2f} | Stop: ${stop:.2f}\n\n"
                    
                    send_telegram_alert(alert_text)
                    print("Dispatched successful Telegram alert!")
                
            except Exception as e:
                print(f"Automated analysis failed: {e}")
                send_telegram_alert(f"⚠️ Engine Error: {e}")
        else:
            print(f"[{datetime.now()}] Market is closed (Weekend). Skipping analysis to save API credits.")
        
        await asyncio.sleep(43200)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_daily_analysis())

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
