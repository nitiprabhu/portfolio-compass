from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import yfinance as yf
import asyncio
from datetime import datetime, timedelta
import os
import httpx
import json

# ── Load .env early so all os.environ.get() calls below succeed ──
if os.path.exists(".env"):
    with open(".env") as _f:
        for _line in _f:
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ.setdefault(_k, _v)

from recommendation_engine import RecommendationEngine
from weekly_backtest import run_backtest_job
from scanner import MarketScanner
from intelligence import NewsIntelligence
from contextlib import asynccontextmanager

# Global Discovery Cache
scanner = MarketScanner()
news_intel = NewsIntelligence()
discovery_results = {"status": "idle", "data": [], "last_run": None}

# Intelligent News Cache
news_results = {"status": "idle", "data": {}, "history": [], "last_run": None, "expires_at": None}

@asynccontextmanager
async def lifespan(app: FastAPI):
    daily_task = asyncio.create_task(background_daily_analysis())
    yield
    daily_task.cancel()
    try: await daily_task
    except asyncio.CancelledError: pass

app = FastAPI(title="Portfolio Compass API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
engine = RecommendationEngine()

# Database Migration & Watchlist Persistence
with sqlite3.connect(engine.db_path) as conn:
    for col in [" peak_price REAL", " news_sentiment INTEGER", " news_json TEXT", " reflection TEXT"]:
        try: conn.execute(f"ALTER TABLE outcomes ADD COLUMN {col}")
        except: pass
    for col in [" last_alert_type TEXT", " last_price REAL", " last_alert_at TEXT"]:
        try: conn.execute(f"ALTER TABLE watchlist ADD COLUMN {col}")
        except: pass

class AnalysisRequest(BaseModel): symbols: List[str]

@app.get("/api/recommendations")
def get_all_recommendations():
    try:
        with sqlite3.connect(engine.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM recommendations ORDER BY created_at DESC LIMIT 50")
            return {"status": "success", "data": [dict(ix) for ix in cursor.fetchall()]}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.post("/api/analyze")
def trigger_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    def run_analysis(symbols):
        mood = news_results.get("data", {}).get("market_mood")
        history = news_results.get("history", [])
        engine.batch_analyze(symbols, market_mood=mood, mood_history=history)
    background_tasks.add_task(run_analysis, req.symbols)
    return {"status": "success", "message": "Analysis started."}

@app.get("/api/news-intelligence")
async def get_news_intelligence(force_refresh: bool = False):
    global news_results
    if not force_refresh and news_results["expires_at"] and datetime.now() < datetime.fromisoformat(news_results["expires_at"]):
        return {"status": "success", "data": news_results["data"], "cached": True}
    try:
        results = await asyncio.to_thread(news_intel.run_daily_scan)
        news_results = {
            "status": "completed", "data": results, 
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": (datetime.now() + timedelta(hours=1)).isoformat()
        }
        return {"status": "success", "data": results, "cached": False}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/portfolio")
def get_portfolio():
    try:
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.symbol, r.recommendation, r.entry_price, r.target_price, r.stop_loss, r.created_at, o.status, r.technical_score
                FROM recommendations r LEFT JOIN outcomes o ON r.id = o.recommendation_id
                WHERE r.recommendation = 'BUY' AND (o.status IS NULL OR o.status = 'OPEN')
                AND r.symbol NOT IN (SELECT symbol FROM watchlist) GROUP BY r.symbol ORDER BY r.created_at DESC
            """)
            positions = cursor.fetchall()

        if not positions: return {"status": "success", "data": [], "summary": {}}
        symbols = [p[0] for p in positions]
        tickers = yf.Tickers(" ".join(symbols))
        portfolio_data = []; total_invested = 0; total_current = 0
        
        for pos in positions:
            symbol, action, entry, target, stop, date, status, tech_score = pos
            if entry is None: continue
            try: live_price = tickers.tickers[symbol].history(period="1d")["Close"].iloc[-1]
            except: live_price = entry
            pnl_pct = ((live_price - entry) / entry) * 100
            total_invested += 10000; total_current += (10000 / entry * live_price)
            
            ai_verdict = "✅ HOLD"
            if tech_score >= 6: ai_verdict = "🔥 BUY MORE"
            elif tech_score < -2: ai_verdict = "⚠️ TRIM"
            
            portfolio_data.append({
                "symbol": symbol, "entry": entry, "live_price": live_price, "pnl_pct": pnl_pct,
                "target": target, "stop": stop, "verdict": ai_verdict, "tech_score": tech_score
            })
            
        return {"status": "success", "data": portfolio_data, "summary": {"total_pnl_pct": ((total_current - total_invested)/total_invested)*100, "total_invested": total_invested, "total_value": total_current}}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/watchlist")
def get_watchlist():
    with sqlite3.connect(engine.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM watchlist ORDER BY added_at DESC")
        return {"status": "success", "data": [dict(r) for r in cursor.fetchall()]}

@app.post("/api/watchlist")
def add_to_watchlist(symbol: str):
    with sqlite3.connect(engine.db_path) as conn:
        expires = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("INSERT OR IGNORE INTO watchlist (symbol, expires_at) VALUES (?, ?)", (symbol.upper(), expires))
    return {"status": "success"}

@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    with sqlite3.connect(engine.db_path) as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.upper(),))
    return {"status": "success"}

@app.get("/api/cost-analysis")
def get_cost_analysis():
    with sqlite3.connect(engine.db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(cost), COUNT(*) FROM api_usage")
        stats = cursor.fetchone()
        return {"status": "success", "summary": {"total_cost": stats[0] or 0, "total_calls": stats[1] or 0}}

@app.get("/api/discover")
def get_discovery_api(): return discovery_results

@app.post("/api/discover/run")
def start_discovery_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_discovery_job)
    return {"status": "started", "message": "Market discovery scan initiated in background"}

# ── Render Free Tier Cron Triggers ─────
# Use these with an external service like Cron-job.org to wake up the server
@app.get("/api/cron/daily")
def trigger_daily_cron(background_tasks: BackgroundTasks):
    """External trigger for 14:00 IST Analysis"""
    print("⏰ External Daily Cron Triggered!")
    symbols = ["AVGO", "GOOGL", "CPER", "URA", "VNT", "CPNG", "SMH", "CNXT", "ARKW", "STEP", "INTC"]
    
    async def run_sync():
        intel = await asyncio.to_thread(news_intel.run_daily_scan)
        mood = intel.get("market_mood", "Neutral")
        if "summary_for_telegram" in intel: send_telegram_alert(intel["summary_for_telegram"])
        for s in symbols:
            engine.analyze_stock(s, bypass_cache=True, save_to_db=True, market_mood=mood)
    
    background_tasks.add_task(run_sync)
    return {"status": "triggered", "task": "daily_analysis"}

@app.get("/api/cron/premarket")
def trigger_premarket_cron(background_tasks: BackgroundTasks):
    """External trigger for 19:00 IST Gap Scan"""
    print("⏰ External Pre-market Cron Triggered!")
    background_tasks.add_task(asyncio.to_thread, scanner.run_premarket_scan)
    return {"status": "triggered", "task": "premarket_gap_scan"}

def run_discovery_job():
    global discovery_results
    discovery_results["status"] = "running"
    res = scanner.run_scan()
    discovery_results = {"status": "completed", "data": res, "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

def send_telegram_alert(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try: httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
        except Exception as e: print(f"Telegram failed: {e}")

async def background_daily_analysis():
    last_sunday_report_date = None
    last_daily_analysis_date = None
    last_premarket_date = None
    
    while True:
        now = datetime.now(); current_day = now.weekday()
        
        # ── Sunday Report ──
        if current_day == 6 and last_sunday_report_date != now.date():
            send_telegram_alert("📊 <b>Weekly Strategic Review</b>\nMarket is closed. Resting.")
            last_sunday_report_date = now.date()

        # ── Daily Analysis (14:00 IST) ──
        if current_day < 5 and now.hour >= 14 and last_daily_analysis_date != now.date():
            symbols = ["AVGO", "GOOGL", "CPER", "URA", "VNT", "CPNG", "SMH", "CNXT", "ARKW", "STEP", "INTC"]
            print(f"[{now}] Running Daily Automation...")
            try:
                # 1. News Intelligence
                intel = await asyncio.to_thread(news_intel.run_daily_scan)
                market_mood = intel.get("market_mood", "Neutral")
                if "summary_for_telegram" in intel: send_telegram_alert(intel["summary_for_telegram"])
                
                # 2. Stock Deep-Dive
                for s in symbols:
                    engine.analyze_stock(s, bypass_cache=True, save_to_db=True, market_mood=market_mood)
                    await asyncio.sleep(2)
                
                # 3. Watchlist Review
                watchlist_alerts = []
                with sqlite3.connect(engine.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT symbol FROM watchlist")
                    for ws_row in cursor.fetchall():
                        ws = ws_row[0]
                        rec = engine.analyze_stock(ws, bypass_cache=True, save_to_db=True, market_mood=market_mood)
                        if rec and rec['recommendation'] == 'BUY':
                            t = yf.Ticker(ws)
                            curr = t.info.get('regularMarketPrice') or rec['entry_price']
                            if abs((curr - rec['entry_price'])/rec['entry_price']) < 0.02:
                                watchlist_alerts.append(f"🔥 <b>{ws}</b>: Near entry at ${curr:.2f}")
                
                if watchlist_alerts: send_telegram_alert("⭐ <b>WATCHLIST HOT ZONE</b>\n" + "\n".join(watchlist_alerts))
                last_daily_analysis_date = now.date()
            except Exception as e: print(f"Daily Error: {e}")

        # ── Pre-Market Gap Scan (19:00 IST) ──
        if current_day < 5 and now.hour >= 19 and last_premarket_date != now.date():
            print(f"[{now}] Running Gap Scan...")
            asyncio.create_task(asyncio.to_thread(scanner.run_premarket_scan))
            last_premarket_date = now.date()
        
        await asyncio.sleep(3600)

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
