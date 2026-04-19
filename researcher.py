from database import RecommendationDB

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
        self.db = RecommendationDB()

    def deep_research(self, symbol: str, question: str) -> dict:
        """
        Gathers raw text data and uses AI to answer a specific research question.
        Uses Context-Augmented Generation (Zero-Dependency RAG).
        """
        try:
            symbol = symbol.upper().strip()
            ticker = yf.Ticker(symbol)
            
            # 1. Gather "Big Data" Context
            info = ticker.info
            profile = {
                "name": info.get("longName"),
                "business_summary": info.get("longBusinessSummary"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "website": info.get("website")
            }
            
            # Latest News
            news_items = ticker.news[:15]
            news_context = ""
            for n in news_items:
                title = n.get('content', {}).get('title', 'No Title')
                pub = n.get('content', {}).get('publisher', 'Unknown')
                news_context += f"- {title} (Source: {pub})\n"

            # Historical Context
            internal_memory = self._get_internal_memory(symbol)

            # 2. Build Researcher Prompt
            prompt = f"""
            You are the "Portfolio Compass Research Lead". 
            Answer this question: {question}
            COMPANY PROFILE: {json.dumps(profile)}
            NEWS: {news_context}
            HISTORY: {internal_memory}
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
        p = self.db._get_placeholder()
        try:
            with self.db.get_connection() as conn:
                from database import RealDictCursor
                cursor = conn.cursor(cursor_factory=RealDictCursor) if self.db.is_postgres else conn.cursor()
                if not self.db.is_postgres: conn.row_factory = sqlite3.Row
                cursor.execute(f"SELECT created_at, recommendation, conviction, technical_score, reasoning FROM recommendations WHERE symbol = {p} ORDER BY created_at DESC LIMIT 3", (symbol,))
                rows = cursor.fetchall()
                if not rows: return "No internal history."
                mem = "OUR RECENT EVALUATIONS:\n"
                for r in rows:
                    mem += f"- {r['created_at']}: {r['recommendation']} ({r['conviction']}%) | Score: {r['technical_score']}\n"
                return mem
        except:
            return "Internal memory lookup failed."

    def _log_usage(self, model: str, in_tokens: int, out_tokens: int):
        cost = (in_tokens * (3.0/1000000)) + (out_tokens * (15.0/1000000))
        self.db.log_api_usage(model, in_tokens, out_tokens, cost)
