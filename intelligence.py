import yfinance as yf
import os
import json
import anthropic
from datetime import datetime
from typing import List, Dict

class NewsIntelligence:
    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.sectors = {
            "XLK": "Technology",
            "XLF": "Financials",
            "XLV": "Healthcare",
            "XLE": "Energy",
            "XLY": "Consumer Cyclical",
            "XLP": "Consumer Defensive",
            "XLI": "Industrials",
            "XLB": "Materials",
            "XLRE": "Real Estate",
            "XLU": "Utilities",
            "XLC": "Communication Services"
        }

    def fetch_market_news(self) -> List[Dict]:
        """Fetches top news for all major sectors and indices"""
        all_news = []
        
        # 1. Fetch general market and major indices news (Increased depth)
        targets = ["stock market news", "^GSPC", "^IXIC", "^DJI", "business news"]
        for target in targets:
            try:
                search = yf.Search(target)
                if hasattr(search, 'news'):
                    all_news.extend(search.news[:10])
            except:
                pass

        # 2. Fetch sector-specific news (Increased to 5 per sector)
        for etf, name in self.sectors.items():
            try:
                ticker = yf.Ticker(etf)
                news = ticker.news[:5] 
                for n in news:
                    n['sector'] = name
                    n['etf'] = etf
                all_news.extend(news)
            except:
                continue
        
        # Remove duplicates based on title if possible
        seen_titles = set()
        unique_news = []
        for n in all_news:
            title = n.get('content', {}).get('title')
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_news.append(n)
        
        return unique_news

    def analyze_news(self, news_items: List[Dict]) -> Dict:
        """Uses AI to distill news into alerts"""
        
        # Prepare news context for AI
        context = ""
        for i, item in enumerate(news_items):
            title = item.get('content', {}).get('title', 'No Title')
            summary = item.get('content', {}).get('summary', '')[:200]
            sector = item.get('sector', 'General')
            context += f"[{sector}] {title}\n{summary}\n\n"

        prompt = f"""
        You are a Senior Market Strategist at a top hedge fund. 
        Analyze the following latest market news and identify 2-3 "High Potential" alerts for today's market.
        
        Focus on:
        1. Sectors getting a major boost (e.g., policy changes, breakout data, major earnings beats).
        2. Specific themes or stocks that are direct beneficiaries of this news.
        3. Simple, actionable advice.

        Current Date: {datetime.now().strftime('%Y-%m-%d')}
        
        News Context:
        {context}

        Return your analysis in the following STRICT JSON format:
        {{
            "market_mood": "Bullish/Bearish/Neutral with 1 sentence reason",
            "top_sectors": ["Sector 1", "Sector 2"],
            "alerts": [
                {{
                    "type": "SECTOR/STOCK",
                    "subject": "Name of Sector or Stock",
                    "catalyst": "What triggered this?",
                    "benefit": "Why is this a buy/hold?",
                    "conviction": 1-100,
                    "action": "BUY/WATCH"
                }}
            ],
            "summary_for_telegram": "A concise, 'cumulative' HTML summary for Telegram. 
            Use emojis. Start with 📰 <b>Morning News Intelligence</b>. 
            Format:
            📰 <b>Morning News Intelligence</b>
            
            <b>Market Mood:</b> [Mood]
            
            🔥 <b>Hot Sectors:</b> [Sector 1], [Sector 2]
            
            🚨 <b>Top Alerts:</b>
            • <b>[Subject]</b>: [Brief why] -> <b>[ACTION]</b>
            
            <i>Read more on your dashboard.</i>"
        }}
        """

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system="You are a Market Intelligence AI.",
            messages=[{"role": "user", "content": prompt}]
        )
        
        try:
            # Extract JSON from response
            text = response.content[0].text
            # Basic JSON extraction if there is fluff
            start = text.find('{')
            end = text.rfind('}') + 1
            return json.loads(text[start:end])
        except Exception as e:
            return {"error": f"Failed to parse AI response: {str(e)}", "raw": response.content[0].text}

    def run_daily_scan(self) -> Dict:
        news = self.fetch_market_news()
        if not news:
            return {"status": "error", "message": "No news found"}
        
        analysis = self.analyze_news(news)
        analysis['last_run'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return analysis
