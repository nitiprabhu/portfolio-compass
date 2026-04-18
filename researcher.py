import os
import sqlite3
import yfinance as yf
from datetime import datetime
import anthropic
import json

class StockResearcher:
    def __init__(self):
        # API Connection
        if os.path.exists(".env"):
            with open(".env") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os.environ[k] = v
        
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.db_path = "recommendations.db"

    def deep_research(self, symbol: str, question: str) -> dict:
        """
        Gathers raw text data and uses AI to answer a specific research question.
        Uses Context-Augmented Generation (Zero-Dependency RAG).
        """
        try:
            symbol = symbol.upper().strip()
            ticker = yf.Ticker(symbol)
            
            # 1. Gather "Big Data" Context
            # Company Profile
            info = ticker.info
            profile = {
                "name": info.get("longName"),
                "business_summary": info.get("longBusinessSummary"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "website": info.get("website")
            }
            
            # Latest News (Up to 15 articles)
            news_items = ticker.news[:15]
            news_context = ""
            for n in news_items:
                title = n.get('content', {}).get('title', 'No Title')
                pub = n.get('content', {}).get('publisher', 'Unknown')
                news_context += f"- {title} (Source: {pub})\n"

            # Historical Context from our own DB
            internal_memory = self._get_internal_memory(symbol)

            # 2. Build Researcher Prompt
            prompt = f"""
            You are the "Portfolio Compass Research Lead". 
            Your goal is to answer a specific investor question based on provided context and internal history.

            --- INVESTOR QUESTION ---
            {question}

            --- COMPANY PROFILE ---
            {json.dumps(profile, indent=2)}

            --- RECENT HEADLINES ---
            {news_context}

            --- INTERNAL EVALUATION HISTORY ---
            {internal_memory}

            --- INSTRUCTIONS ---
            1. Be objective and skeptical. Look for risks.
            2. Cross-reference the news with the company profile.
            3. If the internal history shows we were previously bullish but news is now bearish, highlight the "Pivot".
            4. Provide a "Bottom Line" at the end.
            5. Return your response in clear Markdown.
            """

            # 3. Call Claude
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )

            # Log API usage
            self._log_usage(response.model, response.usage.input_tokens, response.usage.output_tokens)

            return {
                "status": "success",
                "symbol": symbol,
                "answer": response.content[0].text,
                "sources_count": len(news_items)
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _get_internal_memory(self, symbol: str) -> str:
        """Retrieves our past AI recommendations for this stock to provide continuity."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT created_at, recommendation, conviction, technical_score, reasoning 
                    FROM recommendations 
                    WHERE symbol = ? 
                    ORDER BY created_at DESC LIMIT 3
                """, (symbol,))
                rows = cursor.fetchall()
                if not rows: return "No internal history for this asset."
                
                mem = "OUR RECENT EVALUATIONS:\n"
                for r in rows:
                    mem += f"- {r['created_at']}: {r['recommendation']} (Conviction: {r['conviction']}%) | Tech Score: {r['technical_score']}\n"
                    mem += f"  Reasoning Snippet: {r['reasoning'][:150]}...\n"
                return mem
        except:
            return "Internal memory lookup failed."

    def _log_usage(self, model: str, in_tokens: int, out_tokens: int):
        """Standardize logging with the main app"""
        try:
            # Pricing for Sonnet 3.5: $3/MT input, $15/MT output
            cost = (in_tokens * (3.0/1000000)) + (out_tokens * (15.0/1000000))
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO api_usage (model, input_tokens, output_tokens, cost) VALUES (?, ?, ?, ?)",
                    (model, in_tokens, out_tokens, cost)
                )
                conn.commit()
        except:
            pass
