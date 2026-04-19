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

# Intelligent News Cache (Cache for 1 hour to save API costs)
news_results = {
    "status": "idle", 
    "data": {}, 
    "history": [], 
    "last_run": None,
    "expires_at": None
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create background tasks
    daily_task = asyncio.create_task(background_daily_analysis())
    
    yield
    
    # Shutdown: Clean up tasks
    daily_task.cancel()
    try:
        await daily_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Portfolio Compass API", lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = RecommendationEngine()

# Database Migration: ensure peak_price and news_sentiment exists
with sqlite3.connect(engine.db_path) as conn:
    try:
        conn.execute("ALTER TABLE outcomes ADD COLUMN peak_price REAL")
    except:
        pass 
    try:
        conn.execute("ALTER TABLE recommendations ADD COLUMN news_sentiment INTEGER")
    except:
        pass
    try:
        conn.execute("ALTER TABLE recommendations ADD COLUMN news_json TEXT")
    except:
        pass
    try:
        conn.execute("ALTER TABLE recommendations ADD COLUMN reflection TEXT")
    except:
        pass
        
    # --- New: Watchlist Alert Persistence ---
    try:
        conn.execute("ALTER TABLE watchlist ADD COLUMN last_alert_type TEXT")
    except: pass
    try:
        conn.execute("ALTER TABLE watchlist ADD COLUMN last_price REAL")
    except: pass
    try:
        conn.execute("ALTER TABLE watchlist ADD COLUMN last_alert_at TEXT")
    except: pass


class AnalysisRequest(BaseModel):
    symbols: List[str]

@app.get("/api/recommendations")
def get_all_recommendations():
    """Returns recommendations for symbols in watchlist or active portfolio — used by the Dashboard table."""
    try:
        with sqlite3.connect(engine.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # Show all recent recommendations
            cursor.execute("""
                SELECT * FROM recommendations 
                ORDER BY created_at DESC LIMIT 50
            """)
            rows = cursor.fetchall()
            return {"status": "success", "data": [dict(ix) for ix in rows]}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/analyze")
def trigger_analysis(req: AnalysisRequest, background_tasks: BackgroundTasks):
    print(f"DEBUG: Triggering analysis for symbols: {req.symbols}")
    def run_analysis(symbols):
        mood = news_results.get("data", {}).get("market_mood")
        history = news_results.get("history", [])
        engine.batch_analyze(symbols, market_mood=mood, mood_history=history)
        
        # ── Send a quick Telegram summary after manual trigger ──
        try:
            with sqlite3.connect(engine.db_path) as conn:
                cursor = conn.cursor()
                # Get last 1 minute recs
                time_threshold = (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("SELECT symbol, recommendation FROM recommendations WHERE created_at > ?", (time_threshold,))
                recs = cursor.fetchall()
            
            if recs:
                summary = "✅ <b>Analysis Complete!</b>\n\n"
                for s, r in recs:
                    summary += f"• {s}: <b>{r}</b>\n"
                send_telegram_alert(summary)
        except:
            pass

    background_tasks.add_task(run_analysis, req.symbols)
    return {"status": "success", "message": f"Started background analysis for {len(req.symbols)} symbols."}

@app.get("/api/accuracy")
def get_accuracy_stats():
    try:
        stats = engine.db.get_accuracy()
        return {"status": "success", "data": stats}
    except Exception as e:
        return {"status": "error", "message": str(e)}

class BacktestRequest(BaseModel):
    symbols: List[str]

@app.post("/api/backtest/run")
def run_backtest_api(req: BacktestRequest, background_tasks: BackgroundTasks):
    try:
        with open("backtest_results.json", "w") as f:
            json.dump({"status": "running", "message": "Backtest is actively processing 90 days of historical data..."}, f)
    except Exception:
        pass
        
    background_tasks.add_task(run_backtest_job, req.symbols)
    return {"status": "success", "message": f"Started 3M backtest for {len(req.symbols)} symbols."}

@app.get("/api/backtest/results")
def get_backtest_results():
    try:
        # Check if a backtest is actively running in the background
        if os.path.exists("backtest_results.json"):
            with open("backtest_results.json", "r") as f:
                data = json.load(f)
            
            if data.get("status") == "running":
                return data
                
        # Otherwise get the most recent backtest from the DB
        recent_runs = engine.db.get_recent_backtests()
        if not recent_runs:
            return {"status": "pending", "message": "No backtest results found yet."}
            
        latest_run = engine.db.get_backtest_by_id(recent_runs[0]["id"])
        return {"status": "success", "data": latest_run["results_json"], "aggregate_stats": latest_run["aggregate_stats"], "run_id": latest_run["id"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/backtests")
def get_past_backtests():
    try:
        runs = engine.db.get_recent_backtests()
        return {"status": "success", "runs": runs}
    except Exception as e:
        return {"status": "error", "message": str(e)}
        
@app.get("/api/backtests/{run_id}")
def get_backtest_by_id(run_id: int):
    try:
        run_data = engine.db.get_backtest_by_id(run_id)
        if not run_data:
            return {"status": "error", "message": "Backtest run not found"}
        return {"status": "success", "data": run_data["results_json"], "aggregate_stats": run_data["aggregate_stats"], "run_id": run_data["id"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/discover")
def get_discovery_results():
    return discovery_results

def run_discovery_job():
    global discovery_results
    def update_progress(msg):
        discovery_results["message"] = msg

    try:
        discovery_results["status"] = "running"
        discovery_results["message"] = "Initializing..."
        results = scanner.run_scan(progress_callback=update_progress)
        discovery_results = {
            "status": "completed",
            "data": results,
            "message": "Scan complete!",
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # ── Send Telegram Alert for Discovery Completion ──
        if results:
            top_3 = results[:3]
            summary = "🔍 <b>Market Discovery Scan Complete!</b>\n\n"
            summary += "AI has identified 3 new high-potential candidates:\n"
            for r in top_3:
                summary += f"• <b>{r['symbol']}</b>: {r['recommendation']} (Conviction: {r['conviction']}%)\n"
            summary += "\nCheck the dashboard for the full list of Mid/Small cap gems."
            send_telegram_alert(summary)
            
        # Persist to disk
        try:
            with open("discovery_cache.json", "w") as f:
                json.dump(discovery_results, f)
        except: pass
    except Exception as e:
        discovery_results = {"status": "error", "message": str(e), "data": [], "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        send_telegram_alert(f"⚠️ Discovery Scan Failed: {e}")

# ── Load Discovery Cache on Startup ──
if os.path.exists("discovery_cache.json"):
    try:
        with open("discovery_cache.json", "r") as f:
            discovery_results = json.load(f)
    except:
        pass

@app.post("/api/discover/run")
def start_discovery_scan(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_discovery_job)
    return {"status": "started", "message": "Market discovery scan initiated in background"}



@app.get("/api/news-intelligence")
async def get_news_intelligence(force_refresh: bool = False):
    global news_results
    
    # Return cached results if fresh (1 hour)
    if not force_refresh and news_results["expires_at"] and datetime.now() < news_results["expires_at"]:
        return {"status": "success", "data": news_results["data"], "cached": True}

    try:
        results = await asyncio.to_thread(news_intel.run_daily_scan)
        news_results = {
            "status": "completed",
            "data": results,
            "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "expires_at": datetime.now() + timedelta(hours=1)
        }
        return {"status": "success", "data": results, "cached": False}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def update_news_cache(results):
    """Helper to update global results and history, then persist to disk"""
    global news_results
    new_entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "mood": results.get("market_mood", "Neutral")
    }
    
    history = news_results.get("history", [])
    if not isinstance(history, list): history = []
    
    # Avoid duplicate entries for same day
    history = [h for h in history if h["date"] != new_entry["date"]]
    history.append(new_entry)
    history.sort(key=lambda x: x["date"], reverse=True)
    history = history[:7]
    
    news_results["status"] = "completed"
    news_results["data"] = results
    news_results["history"] = history
    news_results["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        with open("news_cache.json", "w") as f:
            json.dump(news_results, f)
    except: pass

def run_news_intelligence_job():
    global news_results
    try:
        print("[News Intelligence] Starting analysis job...")
        news_results["status"] = "running"
        results = news_intel.run_daily_scan()
        
        update_news_cache(results)
        print(f"[News Intelligence] Analysis complete. Alerts found: {len(results.get('alerts', []))}")
        
        # ── Send Telegram Alert ──
        if "summary_for_telegram" in results:
            print("[News Intelligence] Sending Telegram alert...")
            send_telegram_alert(results["summary_for_telegram"])
            
    except Exception as e:
        print(f"[News Intelligence] CRITICAL ERROR: {e}")
        news_results["status"] = "error"
        news_results["message"] = str(e)
        news_results["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        send_telegram_alert(f"⚠️ News Analysis Failed: {e}")

@app.post("/api/news-intelligence/run")
def start_news_analysis(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_news_intelligence_job)
    return {"status": "started", "message": "Daily news analysis initiated in background"}

# ── Load News Cache on Startup ──
if os.path.exists("news_cache.json"):
    try:
        with open("news_cache.json", "r") as f:
            news_results = json.load(f)
    except:
        pass


@app.get("/api/portfolio")
def get_portfolio():
    try:
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.symbol, r.recommendation, r.entry_price, r.target_price, r.stop_loss, r.created_at, o.status
                FROM recommendations r
                LEFT JOIN outcomes o ON r.id = o.recommendation_id
                WHERE r.recommendation = 'BUY' AND (o.status IS NULL OR o.status = 'OPEN')
                AND r.symbol NOT IN (SELECT symbol FROM watchlist)
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
        
        with sqlite3.connect(engine.db_path) as conn:
            for pos in positions:
                symbol, action, entry, target, stop, date, status = pos
                if entry is None: continue

                
                try:
                    live_price = tickers.tickers[symbol].history(period="1d")["Close"].iloc[-1]
                except:
                    live_price = entry
                    
                # Trailing Stop Logic
                # Link to latest recommendation to fix Accuracy tracking
                cursor.execute("SELECT id FROM recommendations WHERE symbol = ? ORDER BY created_at DESC LIMIT 1", (symbol,))
                rec_row = cursor.fetchone()
                rec_id = rec_row[0] if rec_row else None

                cursor.execute("SELECT peak_price FROM outcomes WHERE symbol = ? AND status = 'OPEN'", (symbol,))
                row = cursor.fetchone()
                
                if row:
                    peak_price = row[0] or entry
                    if live_price > peak_price:
                        peak_price = live_price
                        conn.execute("UPDATE outcomes SET peak_price = ?, current_price = ? WHERE symbol = ? AND status = 'OPEN'", (peak_price, live_price, symbol))
                else:
                    peak_price = max(entry, live_price)
                    # Insert with recommendation_id to enable accuracy calculation
                    conn.execute("""
                        INSERT INTO outcomes (symbol, entry_price, current_price, peak_price, status, recommendation_id)
                        VALUES (?, ?, ?, ?, 'OPEN', ?)
                    """, (symbol, entry, live_price, peak_price, rec_id))
                
                # Dynamic Trailing Stop (10% below peak, but never below original stop)
                active_stop = None
                if peak_price is not None:
                    active_stop = peak_price * 0.90
                    if stop is not None:
                        active_stop = max(stop, active_stop)
                
                pnl_pct = ((live_price - entry) / entry) * 100
                shares = 10000 / entry
                total_invested += 10000
                total_current += (shares * live_price)
                
                alert = "ON TRACK"
                if target is not None and live_price >= target: alert = "🎯 HIT TARGET"
                elif active_stop is not None and live_price <= active_stop: alert = "🛑 STOP TRIGGERED"
                elif pnl_pct < -5: alert = "⚠️ UNDERPERFORMING"
                elif active_stop is not None and stop is not None and active_stop > stop: alert = f"🛡️ TRAILING STOP: ${active_stop:.2f}"
                    
                # Get latest technical score and recommendation for AI verdict
                cursor.execute("""
                    SELECT technical_score, recommendation 
                    FROM recommendations 
                    WHERE symbol = ? 
                    ORDER BY created_at DESC LIMIT 1
                """, (symbol,))
                latest_rec = cursor.fetchone()
                tech_score = (latest_rec[0] if (latest_rec and latest_rec[0] is not None) else 0)
                
                # AI Verdict Logic
                if tech_score >= 6: ai_verdict = "🔥 BUY MORE"
                elif tech_score >= 2: ai_verdict = "✅ HOLD"
                elif tech_score >= -2: ai_verdict = "⚖️ NEUTRAL"
                else: ai_verdict = "⚠️ TRIM"
                
                # Proximity analysis
                dist_to_stop = 0
                if active_stop is not None:
                    dist_to_stop = ((live_price - active_stop) / live_price) * 100
                
                dist_to_target = 0
                if target is not None:
                    dist_to_target = ((target - live_price) / live_price) * 100
                
                portfolio_data.append({
                    "symbol": symbol,
                    "entry": entry,
                    "live_price": live_price,
                    "pnl_pct": pnl_pct,
                    "target": target,
                    "stop": active_stop,
                    "alert": alert,
                    "verdict": ai_verdict,
                    "tech_score": tech_score,
                    "dist_to_stop": dist_to_stop,
                    "dist_to_target": dist_to_target
                })
            conn.commit()
            
        summary = {
            "total_pnl_pct": ((total_current - total_invested) / total_invested) * 100 if total_invested else 0,
            "total_invested": total_invested,
            "total_value": total_current
        }
            
        return {"status": "success", "data": portfolio_data, "summary": summary}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/watchlist")
def get_watchlist():
    try:
        with sqlite3.connect(engine.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM watchlist ORDER BY added_at DESC")
            items = [dict(row) for row in cursor.fetchall()]
            
            # Get paper trades for these symbols
            cursor.execute("SELECT * FROM paper_trades WHERE status = 'OPEN'")
            trades = {row['symbol']: dict(row) for row in cursor.fetchall()}
            
            for item in items:
                item['trade'] = trades.get(item['symbol'])
                
            return {"status": "success", "data": items}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/watchlist")
def add_to_watchlist(symbol: str):
    print(f"DEBUG: Adding {symbol} to watchlist")
    try:
        symbol = symbol.upper().strip()
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            # 3 month expiry
            expires_at = (datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                "INSERT OR IGNORE INTO watchlist (symbol, expires_at) VALUES (?, ?)",
                (symbol, expires_at)
            )
            conn.commit()
        return {"status": "success", "message": f"{symbol} added to watchlist"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/api/watchlist/{symbol}")
def remove_from_watchlist(symbol: str):
    try:
        symbol = symbol.upper().strip()
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
            conn.commit()
        return {"status": "success", "message": f"{symbol} removed from watchlist"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/cost-analysis")
def get_cost_analysis():
    try:
        with sqlite3.connect(engine.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Total stats
            cursor.execute("SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost) FROM api_usage")
            stats = cursor.fetchone()
            total_calls = stats[0] or 0
            total_cost = stats[3] or 0
            
            # Today's stats
            cursor.execute("SELECT SUM(cost) FROM api_usage WHERE timestamp > date('now')")
            today_cost = cursor.fetchone()[0] or 0
            
            # Monthly projection
            cursor.execute("SELECT (julianday('now') - julianday(MIN(timestamp))) + 1 FROM api_usage")
            days_tracked_row = cursor.fetchone()
            days_tracked = days_tracked_row[0] if days_tracked_row and days_tracked_row[0] else 1
            avg_daily_cost = total_cost / days_tracked
            monthly_projection = avg_daily_cost * 30
            
            # Recent usage
            cursor.execute("SELECT * FROM api_usage ORDER BY timestamp DESC LIMIT 10")
            recent_items = [dict(row) for row in cursor.fetchall()]
            
            return {
                "status": "success",
                "summary": {
                    "total_calls": total_calls,
                    "total_cost": round(total_cost, 4),
                    "today_cost": round(today_cost, 4),
                    "monthly_projection": round(monthly_projection, 2)
                },
                "history": recent_items
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/paper-trades")
def get_paper_trades():
    try:
        with sqlite3.connect(engine.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM paper_trades ORDER BY opened_at DESC")
            return {"status": "success", "data": [dict(row) for row in cursor.fetchall()]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def send_telegram_alert(message: str):
    """Fires a message directly to your Telegram. Works for any alert type."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("⚠️  Telegram credentials missing — skipping alert.")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        r = httpx.post(url, json=payload, timeout=10.0)
        if r.status_code == 200:
            print("✅ Telegram alert sent successfully!")
        else:
            print(f"❌ Telegram API error: {r.status_code} — {r.text}")
    except Exception as e:
        print(f"❌ Telegram send failed: {e}")


def send_weekly_status():
    """Calculates and sends a performance summary every Sunday."""
    try:
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            # 1. Total Stats
            cursor.execute("SELECT COUNT(*), AVG(return_pct), MAX(return_pct) FROM outcomes WHERE check_date > datetime('now', '-7 days')")
            total_trades, avg_return, max_return = cursor.fetchone()
            
            # 2. Top Performer
            cursor.execute("SELECT symbol, return_pct FROM outcomes WHERE check_date > datetime('now', '-7 days') ORDER BY return_pct DESC LIMIT 1")
            top = cursor.fetchone()
            
            # 3. Active Portfolio Value
            cursor.execute("SELECT SUM(current_price * 10000 / entry_price) FROM outcomes WHERE status = 'OPEN'")
            portfolio_value = cursor.fetchone()[0] or 0

        # Use zero as default for formatting
        display_avg = avg_return if avg_return is not None else 0.0
        display_top_name = top[0] if top else "N/A"
        display_top_val = top[1] if top else 0.0
        
        msg = (
            f"📊 <b>Weekly Strategic Review</b> 📊\n\n"
            f"✨ <b>Activity:</b> {total_trades or 0} active positions tracked\n"
            f"📈 <b>Avg Return:</b> {display_avg:.2f}% (this week)\n"
            f"🚀 <b>Best Performer:</b> {display_top_name} (+{display_top_val:.1f}%)\n"
            f"💰 <b>Est. Portfolio:</b> ${portfolio_value:,.2f}\n\n"
            f"<i>Market is closed. Have a great weekend!</i>"
        )
        send_telegram_alert(msg)
    except Exception as e:
        print(f"Weekly report error: {e}")


def check_sector_concentration() -> Optional[str]:
    """Returns a warning message if any single sector exceeds 40% of active BUY positions."""
    sector_map = {
        "AVGO": "Technology", "GOOGL": "Technology", "SMH": "Technology", "INTC": "Technology",
        "ARKW": "Technology", "STEP": "Financial Services", "VNT": "Industrials", "CPNG": "Consumer Cyclical",
        "CPER": "Basic Materials", "URA": "Energy", "CNXT": "International/ETF"
    }
    try:
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            # Check BUY recommendations from the last 7 days
            threshold = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("SELECT symbol FROM recommendations WHERE recommendation='BUY' AND created_at > ?", (threshold,))
            active_buys = [r[0] for r in cursor.fetchall()]
        
        if not active_buys:
            return None
        
        sector_counts = {}
        for sym in active_buys:
            sector = sector_map.get(sym, "Other")
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
        
        total = len(active_buys)
        for sector, count in sector_counts.items():
            pct = (count / total) * 100
            if pct > 40:
                return (
                    f"🚥 <b>Sector Concentration Warning</b>\n\n"
                    f"Your portfolio is <b>{pct:.0f}% {sector}</b> ({count}/{total} positions).\n"
                    f"Consider diversifying into other sectors to reduce correlated risk.\n"
                    f"If {sector} drops, ALL your positions drop together."
                )
        return None
    except Exception as e:
        print(f"Sector check error: {e}")
        return None


def monitor_portfolio_alerts():
    """Scans open positions and fires Telegram when stops or targets are hit."""
    try:
        with sqlite3.connect(engine.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT r.symbol, r.entry_price, r.target_price, r.stop_loss, o.peak_price
                FROM recommendations r
                LEFT JOIN outcomes o ON r.symbol = o.symbol AND o.status = 'OPEN'
                WHERE r.recommendation = 'BUY'
                ORDER BY r.created_at DESC
            """)
            positions = cursor.fetchall()
        
        for symbol, entry, target, stop, peak_price in positions:
            if not entry or not target or not stop:
                continue
            try:
                live_price = yf.Ticker(symbol).history(period="1d")["Close"].iloc[-1]
            except:
                continue
            
            peak = peak_price or entry
            trailing_stop = max(stop, peak * 0.90)
            
            if live_price >= target:
                send_telegram_alert(
                    f"🎯 <b>TARGET HIT — {symbol}</b>\n\n"
                    f"💵 Entry: ${entry:.2f}\n"
                    f"✅ Live Price: ${live_price:.2f} (Target was ${target:.2f})\n"
                    f"📈 Gain: +{((live_price - entry) / entry * 100):.1f}%\n\n"
                    f"Consider booking partial or full profits!"
                )
            elif live_price <= trailing_stop:
                send_telegram_alert(
                    f"🛑 <b>STOP TRIGGERED — {symbol}</b>\n\n"
                    f"💵 Entry: ${entry:.2f}\n"
                    f"⛔ Live Price: ${live_price:.2f} (Stop was ${trailing_stop:.2f})\n"
                    f"📉 Loss: {((live_price - entry) / entry * 100):.1f}%\n\n"
                    f"Exit position to protect capital."
                )
    except Exception as e:
        print(f"Portfolio monitor error: {e}")


async def background_daily_analysis():
    """Runs automatically once per day to update analysis and handle reports"""
    last_sunday_report_date = None
    last_daily_analysis_date = None
    last_premarket_date = None
    
    while True:
        now = datetime.now()
        current_day = now.weekday()
        
        # ── Sunday Weekly Report & Discovery Scan ─────
        if current_day == 6 and last_sunday_report_date != now.date():
            # Safely check if we already have a successful run today in the cache
            last_run = discovery_results.get("last_run")
            cached_run_date = last_run.split(" ")[0] if last_run else ""
            
            if cached_run_date == now.strftime("%Y-%m-%d"):
                print(f"[{now}] Discovery scan already completed today. Skipping.")
                last_sunday_report_date = now.date()
                continue

            print(f"[{now}] Processing Weekly Sunday Status...")
            send_weekly_status()
            
            # Also run the expensive Discovery Scan automatically on Sundays
            print(f"[{now}] Starting Automated Market Discovery Scan...")
            asyncio.create_task(asyncio.to_thread(run_discovery_job))
            
            last_sunday_report_date = now.date()

        # ── Daily Analysis (Monday–Friday during US Pre-market: ~14:00 IST / 04:30 ET) ─────
        if current_day < 5 and now.hour >= 14 and last_daily_analysis_date != now.date():
            symbols_to_track = ["AVGO", "GOOGL", "CPER", "URA", "VNT", "CPNG", "SMH", "CNXT", "ARKW", "STEP", "INTC"]
            try:
                print(f"[{now}] Executing Automated Daily Analysis...")
                
                # ── News Intelligence Scan FIRST ─────
                print(f"[{now}] Processing News Intelligence...")
                # We await this so we have the mood for the subsequent analysis
                try:
                    results = await asyncio.to_thread(news_intel.run_daily_scan)
                    news_results = {
                        "status": "completed",
                        "data": results,
                        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "expires_at": datetime.now() + timedelta(hours=1)
                    }
                    market_mood = results.get("market_mood")
                    
                    if "summary_for_telegram" in results:
                        send_telegram_alert(results["summary_for_telegram"])
                        
                    with open("news_cache.json", "w") as f:
                        json.dump(news_results, f)
                except Exception as e:
                    print(f"News automation error: {e}")
                    market_mood = "Neutral"

                # ── Stock Deep-Dive Analysis ─────
                for symbol in symbols_to_track:
                    print(f"Analyzing {symbol}...")
                    engine.analyze_stock(symbol, bypass_cache=True, save_to_db=True, market_mood=market_mood)
                    await asyncio.sleep(2)
                
                last_daily_analysis_date = now.date()
                print(f"[{now}] Automated Daily Analysis Complete.")
            except Exception as e:
                print(f"ERROR in daily automation: {e}")

        # ── PRE-MARKET GAP SCAN (Monday–Friday at ~19:00 IST / 09:30 ET) ─────
        if current_day < 5 and now.hour >= 19 and last_premarket_date != now.date():
            print(f"[{now}] Executing Automated Pre-Market Gap Scan...")
            asyncio.create_task(asyncio.to_thread(scanner.run_premarket_scan))
            last_premarket_date = now.date()
                        
                    with open("news_cache.json", "w") as f:
                        json.dump(news_results, f)
                except Exception as ne:
                    print(f"News Analysis failed: {ne}")
                    market_mood = None

                # ── Full Analysis with News Integration ─────
                mood_history = news_results.get("history", [])
                engine.batch_analyze(symbols_to_track, market_mood=market_mood, mood_history=mood_history)
                
                
                # Check for BUY Alerts
                time_threshold = (now - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
                with sqlite3.connect(engine.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT symbol, recommendation, conviction, entry_price, target_price, stop_loss 
                        FROM recommendations 
                        WHERE created_at > ? AND recommendation = 'BUY'
                    """, (time_threshold,))
                    fresh_buys = cursor.fetchall()
                
                if fresh_buys:
                    alert_text = "🚨 <b>Portfolio Compass — New BUY Signals</b> 🚨\n\n"
                    for b in fresh_buys:
                        sym, action, conv, entry, target, stop = b
                        alert_text += f"📈 <b>{sym}</b>: {action} ({conv}% Conviction)\n"
                        alert_text += f"💵 Entry: ${entry:.2f} | Target: ${target:.2f} | Stop: ${stop:.2f}\n\n"
                    send_telegram_alert(alert_text)

                # ── Critical Event Detector (Premium Alerts) ─────
                print(f"[{now}] Scanning for Critical Portfolio Events...")
                portfolio_res = get_portfolio()
                if portfolio_res['status'] == 'success':
                    for item in portfolio_res['data']:
                        alert_msgs = []
                        # 1. Stop Loss Proximity (< 2.5%)
                        if item['dist_to_stop'] < 2.5 and item['alert'] != "🛑 STOP TRIGGERED":
                            alert_msgs.append(f"🚨 <b>CRITICAL:</b> {item['symbol']} is only {item['dist_to_stop']:.1f}% away from Stop Loss!")
                        
                        # 2. Verdict Crash (TRIM required on high-value position)
                        if item['verdict'] == "⚠️ TRIM" and item['pnl_pct'] > 5:
                            alert_msgs.append(f"📉 <b>WARNING:</b> AI downgraded {item['symbol']} to TRIM while you are in profit. Consider locking in gains!")

                        # 3. Target Proximity (> 95% to target)
                        if item['dist_to_target'] < 3 and item['alert'] != "🎯 HIT TARGET":
                            alert_msgs.append(f"🎯 <b>SOON:</b> {item['symbol']} is approaching target ({item['dist_to_target']:.1f}% left)!")

                        if alert_msgs:
                            send_telegram_alert("\n".join(alert_msgs))
                
                # ── Watchlist Paper Trading ─────
                print(f"[{now}] Processing Watchlist & Paper Trading...")
                with sqlite3.connect(engine.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT symbol FROM watchlist")
                    watch_symbols = [row[0] for row in cursor.fetchall()]
                
                for ws in watch_symbols:
                    rec = engine.analyze_stock(ws, bypass_cache=True, save_to_db=True)
                    if not rec: continue
                    
                    price = rec['entry_price']
                    with sqlite3.connect(engine.db_path) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, quantity FROM paper_trades WHERE symbol = ? AND status = 'OPEN'", (ws,))
                        active_trade = cursor.fetchone()
                        
                        if rec['recommendation'] == 'BUY':
                            if not active_trade:
                                # Start new paper trade with $100
                                qty = 100.0 / price
                                cursor.execute("""
                                    INSERT INTO paper_trades (symbol, quantity, entry_price, current_price, total_investment, current_value, status)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (ws, qty, price, price, 100.0, 100.0, 'OPEN'))
                                print(f"  PAPER BUY: {ws} at ${price} ($100 lot)")
                        
                        elif rec['recommendation'] == 'SELL' and active_trade:
                            # Close position
                            cursor.execute("""
                                UPDATE paper_trades 
                                SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP, current_price = ?
                                WHERE id = ?
                            """, (price, active_trade[0]))
                            print(f"  PAPER SELL: {ws} at ${price}")
                        
                        # Update current price for all open watchlist positions
                        cursor.execute("UPDATE paper_trades SET current_price = ?, current_value = quantity * ? WHERE symbol = ? AND status = 'OPEN'", (price, price, ws))
                    
                monitor_portfolio_alerts()
                
                # ── Critical Event Detector (Premium Alerts) ─────
                print(f"[{now}] Scanning for Critical Portfolio Events...")
                portfolio_res = get_portfolio()
                if portfolio_res['status'] == 'success':
                    for item in portfolio_res['data']:
                        alert_msgs = []
                        # 1. Stop Loss Proximity (< 2.5%)
                        if item['dist_to_stop'] < 2.5 and item['alert'] != "🛑 STOP TRIGGERED":
                            alert_msgs.append(f"🚨 <b>CRITICAL:</b> {item['symbol']} is only {item['dist_to_stop']:.1f}% away from Stop Loss!")
                        
                        # 2. Verdict Crash (TRIM required on high-value position)
                        if item['verdict'] == "⚠️ TRIM" and item['pnl_pct'] > 5:
                            alert_msgs.append(f"📉 <b>WARNING:</b> AI downgraded {item['symbol']} to TRIM while you are in profit. Consider locking in gains!")

                        # 3. Target Proximity (> 95% to target)
                        if item['dist_to_target'] < 3 and item['alert'] != "🎯 HIT TARGET":
                            alert_msgs.append(f"🎯 <b>SOON:</b> {item['symbol']} is approaching target ({item['dist_to_target']:.1f}% left)!")

                        if alert_msgs:
                            send_telegram_alert("\n".join(alert_msgs))
                
                # ── Watchlist Paper Trading & Hot Zone Detection ─────
                print(f"[{now}] Processing Watchlist & Paper Trading...")
                watchlist_alerts = []
                with sqlite3.connect(engine.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT symbol FROM watchlist")
                    watch_symbols = [row[0] for row in cursor.fetchall()]
                
                for ws in watch_symbols:
                    rec = engine.analyze_stock(ws, bypass_cache=True, save_to_db=True)
                    if not rec: continue
                    
                    price = rec['entry_price']
                    target = rec['target_price']
                    signal = rec['recommendation']
                    
                    # Entry Zone Detection (within 2% of entry target)
                    if signal == "BUY" and price > 0:
                        # Fetch the absolute latest live price for the alert
                        t = yf.Ticker(ws)
                        curr = t.info.get('regularMarketPrice') or price
                        proximity = ((curr - price) / price) * 100
                        if abs(proximity) < 2.0:
                            watchlist_alerts.append(f"🔥 <b>{ws}:</b> Ready for entry (${curr:.2f}). Near target of ${price:.2f}")

                    with sqlite3.connect(engine.db_path) as conn:
                        cursor = conn.cursor()
                        # ... Paper trading logic remains same ...
                        cursor.execute("SELECT id, quantity FROM paper_trades WHERE symbol = ? AND status = 'OPEN'", (ws,))
                        active_trade = cursor.fetchone()
                        if signal == 'BUY':
                            if not active_trade:
                                qty = 100.0 / price
                                cursor.execute("INSERT INTO paper_trades (symbol, quantity, entry_price, current_price, total_investment, current_value, status) VALUES (?, ?, ?, ?, ?, ?, ?)", (ws, qty, price, price, 100.0, 100.0, 'OPEN'))
                        elif signal == 'SELL' and active_trade:
                            cursor.execute("UPDATE paper_trades SET status = 'CLOSED', closed_at = CURRENT_TIMESTAMP, current_price = ? WHERE id = ?", (price, active_trade[0]))
                        cursor.execute("UPDATE paper_trades SET current_price = ?, current_value = quantity * ? WHERE symbol = ? AND status = 'OPEN'", (price, price, ws))
                        conn.commit()
                
                if watchlist_alerts:
                    send_telegram_alert("⭐ <b>DAILY WATCHLIST HOT ZONE</b>\n" + "\n".join(watchlist_alerts))
                
                sector_warning = check_sector_concentration()
                if sector_warning:
                    send_telegram_alert(sector_warning)
                
                last_daily_analysis_date = now.date()
                print(f"[{now}] Daily Analysis complete.")

            except Exception as e:
                print(f"Automated analysis failed: {e}")
                send_telegram_alert(f"⚠️ Engine Error: {e}")
        
        elif current_day >= 5 and current_day != 6: # Saturday
            if last_daily_analysis_date != now.date():
                print(f"[{now}] Market is closed. Resting.")
                last_daily_analysis_date = now.date()
        
        await asyncio.sleep(3600)  # Check every hour, but execute only once per day


@app.get("/api/test-telegram")
def test_telegram():
    """Quick test endpoint — call this to verify Telegram is wired correctly"""
    send_telegram_alert(
        "✅ <b>Portfolio Compass — Bot Connected!</b>\n\n"
        "Your alerts are now live:\n"
        "📈 BUY signals → instant alert\n"
        "🛑 Stop-Loss hit → instant alert\n"
        "🎯 Target hit → instant alert\n"
        "🚥 Sector overload → instant warning"
    )
    return {"status": "success", "message": "Test message dispatched to Telegram"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
