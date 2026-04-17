from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import sqlite3
import yfinance as yf
import asyncio
from datetime import datetime

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

async def background_daily_analysis():
    """Runs automatically every day to keep the dashboard constantly updated without human interaction"""
    while True:
        # Check if it is a weekend (5 = Saturday, 6 = Sunday)
        current_day = datetime.now().weekday()
        if current_day < 5:
            # Default active watchlist tracked by the engine
            symbols_to_track = ["AAPL", "NVDA", "MSFT", "SOXX", "SOXL", "ASTS", "RKLB", "IOT", "PLTR"]
            try:
                print(f"[{datetime.now()}] Executing Automated Daily Analysis Cron...")
                engine.batch_analyze(symbols_to_track)
            except Exception as e:
                print(f"Automated analysis failed: {e}")
        else:
            print(f"[{datetime.now()}] Market is closed (Weekend). Skipping analysis to save API credits.")
        
        # Sleep for 12 hours between autonomous checks
        await asyncio.sleep(43200)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_daily_analysis())

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
