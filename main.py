from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Depends
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

# ── Load .env early ──
if os.path.exists(".env"):
    with open(".env") as _f:
        for _line in _f:
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ.setdefault(_k, _v)

from recommendation_engine import RecommendationEngine
try:
    from psycopg2.extras import RealDictCursor
except ImportError:
    RealDictCursor = None
from weekly_backtest import run_backtest_job
from scanner import MarketScanner
from intelligence import NewsIntelligence
from update_outcomes import update_all_outcomes
from contextlib import asynccontextmanager

# Global Discovery Cache
scanner = MarketScanner()
news_intel = NewsIntelligence()
discovery_results = {"status": "idle", "data": [], "last_run": None}

# Intelligent News Cache
news_results = {"status": "idle", "data": {}, "history": [], "last_run": None, "expires_at": None}

app = FastAPI(title="Portfolio Compass API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
engine = RecommendationEngine()

# Database Migration & Watchlist Persistence
with engine.db.get_connection() as conn:
    cursor = conn.cursor()
    for col in [" peak_price REAL", " news_sentiment INTEGER", " news_json TEXT", " reflection TEXT"]:
        try: cursor.execute(f"ALTER TABLE outcomes ADD COLUMN {col}")
        except: pass
    for col in [" last_alert_type TEXT", " last_price REAL", " last_alert_at TEXT"]:
        try: cursor.execute(f"ALTER TABLE watchlist ADD COLUMN {col}")
        except: pass
    if not engine.db.is_postgres:
        conn.commit()

class AnalysisRequest(BaseModel): symbols: List[str]

@app.get("/api/recommendations")
def get_all_recommendations():
    try:
        with engine.db.get_connection() as conn:
            if engine.db.is_postgres:
                cursor = conn.cursor(cursor_factory=RealDictCursor)
            else:
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
    
    # 1. Check database first if not forced
    if not force_refresh:
        latest = engine.db.get_latest_news_intelligence()
        if latest:
            # Sync global state for other components
            news_results = {
                "status": "completed", 
                "data": latest["data"], 
                "last_run": str(latest["run_date"]),
                "expires_at": str(latest["expires_at"])
            }
            return {"status": "success", "data": latest["data"], "cached": True}

    # 2. Otherwise run new scan
    try:
        results = await asyncio.to_thread(news_intel.run_daily_scan)
        
        # 3. Save to database with 7 day TTL
        engine.db.save_news_intelligence(results, ttl_days=7)
        
        news_results = {
            "status": "completed", "data": results, 
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": (datetime.now() + timedelta(days=7)).isoformat()
        }
        return {"status": "success", "data": results, "cached": False}
    except Exception as e: return {"status": "error", "message": str(e)}

@app.get("/api/portfolio")
def get_portfolio():
    try:
        with engine.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.symbol, r.recommendation, r.entry_price, r.target_price, r.stop_loss, r.created_at, o.status, r.technical_score
                FROM recommendations r LEFT JOIN outcomes o ON r.id = o.recommendation_id
                WHERE r.recommendation = 'BUY' AND (o.status IS NULL OR o.status = 'OPEN')
                AND r.symbol NOT IN (SELECT symbol FROM watchlist) GROUP BY 1,2,3,4,5,6,7,8 ORDER BY r.created_at DESC
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
    with engine.db.get_connection() as conn:
        if engine.db.is_postgres:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
        cursor.execute("SELECT * FROM watchlist ORDER BY added_at DESC")
        return {"status": "success", "data": [dict(r) for r in cursor.fetchall()]}

@app.post("/api/watchlist")
def add_to_watchlist(symbol: str):
    p = engine.db._get_placeholder()
    with engine.db.get_connection() as conn:
        cursor = conn.cursor()
        expires = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
        if engine.db.is_postgres:
            cursor.execute("INSERT INTO watchlist (symbol, expires_at) VALUES (%s, %s) ON CONFLICT (symbol) DO NOTHING", (symbol.upper(), expires))
        else:
            cursor.execute("INSERT OR IGNORE INTO watchlist (symbol, expires_at) VALUES (?, ?)", (symbol.upper(), expires))
        if not engine.db.is_postgres:
            conn.commit()
    return {"status": "success"}

@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    p = engine.db._get_placeholder()
    with engine.db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM watchlist WHERE symbol = {p}", (symbol.upper(),))
        if not engine.db.is_postgres:
            conn.commit()
    return {"status": "success"}

@app.get("/api/cost-analysis")
def get_cost_analysis():
    with engine.db.get_connection() as conn:
        if engine.db.is_postgres:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
        cursor.execute("SELECT SUM(cost) as total_cost, COUNT(*) as total_calls FROM api_usage")
        stats = cursor.fetchone()
        return {"status": "success", "summary": {"total_cost": stats[0] if not engine.db.is_postgres else stats['total_cost'] or 0, "total_calls": stats[1] if not engine.db.is_postgres else stats['total_calls'] or 0}}

@app.get("/api/discover")
def get_discovery_api():
    global discovery_results
    
    # Try to load from database first
    latest = engine.db.get_latest_discovery_results()
    if latest:
        discovery_results = {
            "status": "completed", 
            "data": latest["data"], 
            "last_run": str(latest["run_date"])
        }
    return discovery_results

@app.post("/api/discover/run")
def trigger_discovery(background_tasks: BackgroundTasks):
    def run_discovery():
        global discovery_results
        discovery_results["status"] = "running"
        res = scanner.run_scan()
        # Persist to database!
        engine.db.save_discovery_results(res)
        discovery_results = {"status": "completed", "data": res, "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    background_tasks.add_task(run_discovery)
    return {"status": "started"}

# ── Refactored Automation Tasks ──

async def task_daily_analysis():
    now = datetime.now()
    # 0. Fetch dynamic symbol list from Watchlist
    symbols = []
    try:
        with engine.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM watchlist")
            symbols = [row[0] for row in cursor.fetchall()]
    except: pass
    
    # Fallback to core leaders if watchlist is empty
    if not symbols:
        symbols = ["AVGO", "GOOGL", "PLTR", "SOFI", "VTI", "SMH", "INTC"]

    print(f"[{now}] Running Daily Automation for {len(symbols)} symbols...")
    try:
        # 1. News Intelligence
        intel = await asyncio.to_thread(news_intel.run_daily_scan)
        engine.db.save_news_intelligence(intel, ttl_days=7)
        market_mood = intel.get("market_mood", "Neutral")
        if "summary_for_telegram" in intel: send_telegram_alert(intel["summary_for_telegram"])
        
        # 2. Stock Deep-Dive
        for s in symbols:
            engine.analyze_stock(s, bypass_cache=True, save_to_db=True, market_mood=market_mood)
            await asyncio.sleep(5)
        
        # 3. Watchlist Review
        watchlist_alerts = []
        with engine.db.get_connection() as conn:
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
        print(f"[{now}] Daily Automation Completed.")
    except Exception as e: 
        print(f"Daily Error: {e}")
        send_telegram_alert(f"❌ <b>Daily Automation Failed</b>\n{str(e)}")

# ── API Cron Endpoints ──

@app.post("/api/cron/daily-analysis")
async def cron_daily_analysis(background_tasks: BackgroundTasks):
    background_tasks.add_task(task_daily_analysis)
    return {"status": "success", "message": "Daily analysis task queued"}

@app.post("/api/cron/premarket-scan")
async def cron_premarket_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(asyncio.to_thread, scanner.run_premarket_scan)
    return {"status": "success", "message": "Pre-market gap scan queued"}

@app.post("/api/cron/weekly-report")
async def cron_weekly_report(background_tasks: BackgroundTasks):
    def run_sunday_strategy():
        send_telegram_alert("📊 <b>Starting Weekly Strategic Review...</b>\nRunning fresh market discovery for the week ahead.")
        res = scanner.run_scan()
        engine.db.save_discovery_results(res)
        send_telegram_alert(f"✅ <b>Weekly Discovery Complete</b>\nFound {len(res)} high-momentum candidates for your watchlist.")
    
    background_tasks.add_task(run_sunday_strategy)
    return {"status": "success", "message": "Weekly strategic discovery queued"}

@app.post("/api/cron/update-outcomes")
async def cron_update_outcomes(background_tasks: BackgroundTasks):
    background_tasks.add_task(asyncio.to_thread, update_all_outcomes)
    return {"status": "success", "message": "Outcome updates queued"}

def send_telegram_alert(message: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try: httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
        except Exception as e: print(f"Telegram failed: {e}")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
