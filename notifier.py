import os
import requests
from dotenv import load_dotenv

load_dotenv()

def send_telegram_alert(symbol, recommendation, conviction, reasoning, price=None, technicals=None):
    """Sends a rich formatted alert to Telegram."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Telegram credentials missing in .env")
        return False
        
    emoji = "🚀" if recommendation == "BUY" else ("📉" if recommendation == "SELL" else "⚖️")
    
    price_text = f"*Approx Price:* ${price:.2f}\n" if price else ""
    
    message = (
        f"{emoji} *NEW DISCOVERY: {symbol}*\n"
        f"---------------------------\n"
        f"*Signal:* {recommendation}\n"
        f"{price_text}"
        f"*Conviction:* {conviction}%\n"
        f"\n"
        f"*AI Reasoning:*\n"
        f"{reasoning[:200]}...\n"
        f"\n"
        f"🔗 [View on Yahoo Finance](https://finance.yahoo.com/quote/{symbol})"
    )
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram notify error: {e}")
        return False

def send_bulk_discovery_alert(findings: list):
    """Sends a single cumulative alert containing all discovered stocks."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id or not findings:
        return False

    summary = "🔍 *Market Discovery: Daily Multi-Bagger Scan*\n"
    summary += "AI has identified the following high-potential setups:\n\n"

    for rec in findings:
        signal = rec.get('recommendation', '').upper()
        if signal not in ["BUY", "SELL"]:
            continue
            
        emoji = "🚀" if signal == "BUY" else "📉"
        symbol = rec['symbol']
        conf = rec['conviction']
        
        # Calculate Potential Upside
        entry = rec.get('entry_price', 0)
        target = rec.get('target_price', 0)
        upside_str = ""
        if entry > 0 and target > 0:
            upside = ((target - entry) / entry) * 100
            upside_str = f" | 📈 *+{upside:.1f}% Upside*"

        summary += f"{emoji} *{symbol}*: {signal} ({conf}% Conf){upside_str}\n"

    # Only send if we actually have filtered findings to report
    if "\n🚀" not in summary and "\n📉" not in summary:
        print("  No BUY/SELL signals found in this scan. Skipping Telegram alert.")
        return

    summary += "\n🔗 [Open Dashboard](https://portfolio-compass-k4aw.onrender.com)"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": summary,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("  ✅ Cumulative Telegram alert sent successfully!")
            return True
        else:
            print(f"  ❌ Telegram Bulk Error: {response.text}")
            return False
    except Exception as e:
        print(f"Telegram notify error: {e}")
        return False

if __name__ == "__main__":
    # Test notification
    send_telegram_alert("TEST", "BUY", 95, "This is a test notification for your new AI Hunter alerts.")
