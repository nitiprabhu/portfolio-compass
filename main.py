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

# ── Load .env early so all os.environ.get() calls below succeed ──
if os.path.exists(".env"):
    with open(".env") as _f:
        for _line in _f:
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.strip().split("=", 1)
                os.environ.setdefault(_k, _v)

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

# Database Migration: ensure peak_price and news_sentiment exists
with sqlite3.connect(engine.db.db_path) as conn:
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
        
        # ── Send a quick Telegram summary after manual trigger ──
        try:
            with sqlite3.connect(engine.db.db_path) as conn:
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
        
        with sqlite3.connect(engine.db.db_path) as conn:
            for pos in positions:
                symbol, action, entry, target, stop, date, status = pos
                if not entry: continue
                
                try:
                    live_price = tickers.tickers[symbol].history(period="1d")["Close"].iloc[-1]
                except:
                    live_price = entry
                    
                # Trailing Stop Logic
                cursor = conn.cursor()
                cursor.execute("SELECT peak_price FROM outcomes WHERE symbol = ? AND status = 'OPEN'", (symbol,))
                row = cursor.fetchone()
                
                if row:
                    peak_price = row[0] or entry
                    if live_price > peak_price:
                        peak_price = live_price
                        conn.execute("UPDATE outcomes SET peak_price = ?, current_price = ? WHERE symbol = ? AND status = 'OPEN'", (peak_price, live_price, symbol))
                else:
                    peak_price = max(entry, live_price)
                    # Insert if it doesn't exist yet but it's an active position
                    conn.execute("""
                        INSERT INTO outcomes (symbol, entry_price, current_price, peak_price, status)
                        VALUES (?, ?, ?, ?, 'OPEN')
                    """, (symbol, entry, live_price, peak_price))
                
                # Dynamic Trailing Stop (10% below peak, but never below original stop)
                active_stop = max(stop, peak_price * 0.90) if stop else peak_price * 0.90
                
                pnl_pct = ((live_price - entry) / entry) * 100
                shares = 10000 / entry
                total_invested += 10000
                total_current += (shares * live_price)
                
                alert = "ON TRACK"
                if live_price >= target: alert = "🎯 HIT TARGET"
                elif live_price <= active_stop: alert = "🛑 STOP TRIGGERED"
                elif pnl_pct < -5: alert = "⚠️ UNDERPERFORMING"
                elif active_stop > stop: alert = f"🛡️ TRAILING STOP: ${active_stop:.2f}"
                    
                portfolio_data.append({
                    "symbol": symbol,
                    "entry": entry,
                    "live_price": live_price,
                    "pnl_pct": pnl_pct,
                    "target": target,
                    "stop": active_stop,
                    "alert": alert
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
        with sqlite3.connect(engine.db.db_path) as conn:
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

        msg = (
            f"📊 <b>Weekly Strategic Review</b> 📊\n\n"
            f"✨ <b>Activity:</b> {total_trades or 0} active positions tracked\n"
            f"📈 <b>Avg Return:</b> {avg_return:.2f}% (this week)\n"
            f"🚀 <b>Best Performer:</b> {top[0] if top else 'N/A'} (+{top[1]:.1f}%)\n"
            f"💰 <b>Est. Portfolio:</b> ${portfolio_value:,.2f}\n\n"
            f"<i>Market is closed. Have a great weekend!</i>"
        )
        send_telegram_alert(msg)
    except Exception as e:
        print(f"Weekly report error: {e}")


def check_sector_concentration() -> Optional[str]:
    """Returns a warning message if any single sector exceeds 40% of active BUY positions."""
    sector_map = {
        "AAPL": "Technology", "NVDA": "Technology", "MSFT": "Technology",
        "AMD": "Technology", "SOXX": "Technology", "SOXL": "Technology",
        "GOOGL": "Technology", "TSLA": "Technology",
        "ASTS": "Industrials", "RKLB": "Industrials",
        "IOT": "Technology", "PLTR": "Technology"
    }
    try:
        with sqlite3.connect(engine.db.db_path) as conn:
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
        with sqlite3.connect(engine.db.db_path) as conn:
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
    """Runs automatically to keep everything updated and handle Sunday reports"""
    last_sunday_report_date = None
    
    while True:
        now = datetime.now()
        current_day = now.weekday()
        
        # ── Sunday Weekly Report ─────
        if current_day == 6 and last_sunday_report_date != now.date():
            print(f"[{now}] Processing Weekly Sunday Status...")
            send_weekly_status()
            last_sunday_report_date = now.date()

        if current_day < 5:  # Monday–Friday only
            symbols_to_track = ["AAPL", "NVDA", "MSFT", "SOXX", "SOXL", "ASTS", "RKLB", "IOT", "PLTR", "AMD", "GOOGL", "TSLA"]
            try:
                print(f"[{now}] Executing Automated Daily Analysis...")
                engine.batch_analyze(symbols_to_track)
                
                # (BUY Alerts code remains same...)
                time_threshold = (now - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
                with sqlite3.connect(engine.db.db_path) as conn:
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

                monitor_portfolio_alerts()
                
                sector_warning = check_sector_concentration()
                if sector_warning:
                    send_telegram_alert(sector_warning)

            except Exception as e:
                print(f"Automated analysis failed: {e}")
                send_telegram_alert(f"⚠️ Engine Error: {e}")
        else:
            if current_day != 6: # Saturday
                print(f"[{now}] Market is closed. Resting.")
        
        await asyncio.sleep(3600)  # Check every hour for easier logic tracking

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_daily_analysis())

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
