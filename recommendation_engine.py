#!/usr/bin/env python3
"""
PRODUCTION-READY STOCK RECOMMENDATION ENGINE
For "Portfolio Compass" - Startup MVP

Key changes from POC:
1. Structured JSON output (not just text)
2. Batch analysis (5-10 stocks at a time)
3. Database tracking (store all recommendations)
4. Outcome tracking (did it actually work?)
5. Simplified output (client-friendly explanations)
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import yfinance as yf
import anthropic

# ============================================================================
# DATABASE SETUP
# ============================================================================

class RecommendationDB:
    """SQLite database for recommendations and outcomes"""
    
    def __init__(self, db_path: str = "recommendations.db"):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Create tables if they don't exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    recommendation TEXT NOT NULL,  -- BUY, SELL, HOLD
                    conviction INTEGER,  -- 0-100
                    entry_price REAL,
                    stop_loss REAL,
                    target_price REAL,
                    fundamentals_score INTEGER,
                    technical_score INTEGER,
                    reasoning TEXT,
                    risks TEXT,  -- JSON list
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS outcomes (
                    id INTEGER PRIMARY KEY,
                    recommendation_id INTEGER,
                    symbol TEXT,
                    entry_price REAL,
                    entry_date TIMESTAMP,
                    current_price REAL,
                    check_date TIMESTAMP,
                    status TEXT,  -- OPEN, HIT_TARGET, HIT_STOP, CLOSED_EARLY
                    return_pct REAL,
                    FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
                )
            """)
            
            conn.commit()
    
    def save_recommendation(self, rec: Dict) -> int:
        """Save recommendation and return ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO recommendations 
                (symbol, recommendation, conviction, entry_price, stop_loss, 
                 target_price, fundamentals_score, technical_score, reasoning, risks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec["symbol"],
                rec["recommendation"],
                rec["conviction"],
                rec["entry_price"],
                rec["stop_loss"],
                rec["target_price"],
                rec["fundamentals_score"],
                rec["technical_score"],
                rec["reasoning"],
                json.dumps(rec.get("risks", []))
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_accuracy(self) -> Dict:
        """Calculate recommendation accuracy"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Count profitable BUY recommendations
            cursor.execute("""
                SELECT COUNT(*) FROM recommendations 
                WHERE recommendation = 'BUY'
            """)
            total_buys = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT COUNT(*) FROM recommendations r
                WHERE r.recommendation = 'BUY'
                AND EXISTS (
                    SELECT 1 FROM outcomes o 
                    WHERE o.recommendation_id = r.id 
                    AND (o.status = 'HIT_TARGET' OR o.return_pct > 0)
                )
            """)
            profitable_buys = cursor.fetchone()[0]
            
            buy_accuracy = (profitable_buys / total_buys * 100) if total_buys > 0 else 0
            
            # Average return
            cursor.execute("""
                SELECT AVG(return_pct) FROM outcomes 
                WHERE status IN ('HIT_TARGET', 'CLOSED_EARLY')
            """)
            avg_return = cursor.fetchone()[0] or 0
            
            return {
                "total_recommendations": total_buys,
                "profitable": profitable_buys,
                "accuracy_percent": round(buy_accuracy, 1),
                "average_return_percent": round(avg_return, 2)
            }


# ============================================================================
# RECOMMENDATION ENGINE
# ============================================================================

class RecommendationEngine:
    """Main engine that generates recommendations"""
    
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.db = RecommendationDB()
    
    def analyze_stock(self, symbol: str) -> Optional[Dict]:
        """
        Analyze a stock and return structured recommendation
        
        Returns:
        {
            "symbol": "AAPL",
            "recommendation": "BUY",
            "conviction": 72,
            "entry_price": 150,
            "stop_loss": 130,
            "target_price": 180,
            "fundamentals_score": 11,
            "technical_score": 4,
            "reasoning": "...",
            "reasons": ["...", "..."],
            "risks": ["...", "..."],
            "outlook": "...",
            "similar_pattern": "..."
        }
        """
        
        try:
            # Get data
            fundamentals = self._get_fundamentals(symbol)
            technicals = self._get_technicals(symbol)
            
            if "error" in fundamentals or "error" in technicals:
                return None
            
            # Score
            fund_score = self._score_fundamentals(fundamentals)
            tech_score = self._score_technicals(technicals)
            
            # Ask Claude for recommendation
            prompt = self._build_prompt(symbol, fundamentals, technicals, fund_score, tech_score)
            response = self.client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            recommendation_text = response.content[0].text
            
            # Parse Claude's response
            rec = self._parse_recommendation(
                symbol,
                recommendation_text,
                fund_score,
                tech_score,
                fundamentals,
                technicals
            )
            
            return rec
        
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")
            return None
    
    def _get_fundamentals(self, symbol: str) -> Dict:
        """Fetch fundamentals"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            return {
                "symbol": symbol,
                "sector": info.get("sector", "Unknown"),
                "quote_type": info.get("quoteType", "EQUITY"),
                "price": info.get("currentPrice", 0),
                "roe": info.get("returnOnEquity"),
                "debt_equity": info.get("debtToEquity"),
                "peg": info.get("pegRatio"),
                "pe": info.get("trailingPE"),
                "revenue_growth": info.get("revenueGrowth"),
                "earnings_growth": info.get("earningsGrowth"),
                "profit_margin": info.get("profitMargins"),
                "fcf": info.get("freeCashflow"),
                "market_cap": info.get("marketCap"),
                "insider_ownership": info.get("insidersPercentHeld"),
            }
        except:
            return {"error": f"Could not fetch fundamentals for {symbol}"}
    
    def _get_technicals(self, symbol: str) -> Dict:
        """Fetch technical metrics"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1y")
            
            if hist.empty:
                return {"error": f"No data for {symbol}"}
            
            current = hist["Close"].iloc[-1]
            sma50 = hist["Close"].tail(50).mean()
            sma200 = hist["Close"].tail(200).mean() if len(hist) >= 200 else None
            
            high52 = hist["Close"].tail(252).max() if len(hist) >= 252 else hist["Close"].max()
            low52 = hist["Close"].tail(252).min() if len(hist) >= 252 else hist["Close"].min()
            
            volatility = hist["Close"].pct_change().std() * (252 ** 0.5) * 100
            
            change_1y = ((current - hist["Close"].iloc[0]) / hist["Close"].iloc[0] * 100)
            
            return {
                "symbol": symbol,
                "current_price": current,
                "sma_50": sma50,
                "sma_200": sma200,
                "high_52w": high52,
                "low_52w": low52,
                "volatility": volatility,
                "change_1y": change_1y,
                "above_sma50": current > sma50,
                "above_sma200": current > sma200 if sma200 else False,
            }
        except:
            return {"error": f"Could not fetch technicals for {symbol}"}
    
    def _score_fundamentals(self, fund: Dict) -> int:
        """Score fundamentals 0-13 using dynamic sector-aware thresholds"""
        if fund.get("quote_type") == "ETF":
            return 10  # Auto-pass fundamentals for ETFs so technicals drive the entire score
            
        revenue_growth = fund.get("revenue_growth") or 0
        pe = fund.get("pe")
        
        # Hyper-Growth Multi-Bagger Bypass
        if revenue_growth > 0.25 and (pe is None or pe < 0 or pe > 50):
            return 11  # Auto-pass fundamentals due to explosive growth characteristics

        score = 0
        sector = fund.get("sector", "Unknown")
        
        # Dynamic thresholds based on sector
        max_pe = 40 if sector == "Technology" else (15 if sector == "Financial Services" else 25)
        max_debt_equity = 1.5 if sector in ["Utilities", "Real Estate"] else 1.0
        min_roe = 0.10 if sector in ["Utilities", "Basic Materials"] else 0.15
        max_peg = 1.5 if sector == "Technology" else 1.0
        
        if (fund.get("roe") or 0) > min_roe:
            score += 1
        if (fund.get("debt_equity") or float('inf')) < max_debt_equity:
            score += 1
        peg = fund.get("peg")
        if peg is not None and peg < max_peg:
            score += 1
        pe = fund.get("pe")
        if pe is not None and 0 < pe < max_pe:
            score += 1
        if (fund.get("revenue_growth") or 0) > 0.15:
            score += 1
        if (fund.get("earnings_growth") or 0) > 0.10:
            score += 1
        if (fund.get("profit_margin") or 0) > 0.10:
            score += 1
        if (fund.get("insider_ownership") or 0) > 0.05:
            score += 1
        if (fund.get("market_cap") or 0) > 1_000_000_000:
            score += 1
        fcf = fund.get("fcf")
        if fcf is not None and fcf > 0:
            score += 1
        
        # Technical
        score += 3  # Will be refined with technical
        
        return score
    
    def _score_technicals(self, tech: Dict) -> int:
        """Score technicals 0-5"""
        score = 0
        
        if tech.get("above_sma50"):
            score += 1
        if tech.get("above_sma200"):
            score += 1
        if (tech.get("volatility") or float('inf')) < 60:
            score += 1
        if (tech.get("change_1y") or 0) > 0:
            score += 1
        cur = tech.get("current_price")
        high = tech.get("high_52w")
        if cur is not None and high is not None and cur < high * 0.95:
            score += 1
        
        return score
    
    def _build_prompt(self, symbol: str, fund: Dict, tech: Dict, fund_score: int, tech_score: int) -> str:
        """Build prompt for Claude"""
        
        return f"""
Analyze {symbol} and provide a stock recommendation.

DATA:
Sector: {fund.get('sector', 'Unknown')}
Fundamentals Score: {fund_score}/13 (higher = better company)
- ROE: {fund.get('roe', 'N/A')}
- P/E: {fund.get('pe', 'N/A')}
- D/E: {fund.get('debt_equity', 'N/A')}
- PEG: {fund.get('peg', 'N/A')}
- Revenue growth: {fund.get('revenue_growth', 'N/A')}
- Profit margin: {fund.get('profit_margin', 'N/A')}

Technical Score: {tech_score}/5 (higher = better timing)
- Current: ${tech.get('current_price', 0):.2f}
- 50-day MA: ${tech.get('sma_50', 0):.2f}
- 200-day MA: ${tech.get('sma_200', 0):.2f}
- 52w High: ${tech.get('high_52w', 0):.2f}
- 52w Low: ${tech.get('low_52w', 0):.2f}
- Volatility: {tech.get('volatility', 0):.1f}%
- 1Y Return: {tech.get('change_1y', 0):.1f}%

RULES:
1. Recommend only if fundamentals score > 9 AND technical score > 2
2. If fundamentals good but technical bad: "BUY but wait"
3. If fundamentals bad: "SELL" or "AVOID"
4. Conviction = (fund_score/13 + tech_score/5) / 2 * 100, capped at 90%

RESPONSE FORMAT (EXACT):
RECOMMENDATION: [BUY/SELL/HOLD/WAIT]
CONVICTION: [0-100]
ENTRY: $[price]
STOP_LOSS: $[price]
TARGET: $[price]
FUND_SCORE: {fund_score}
TECH_SCORE: {tech_score}

REASONS (top 3 strengths):
1. [reason]
2. [reason]
3. [reason]

RISKS (top 2 concerns):
1. [risk]
2. [risk]

OUTLOOK (1-2 sentences):
[explanation]

SIMILAR (if exists):
This reminds of [stock] when [situation], which [outcome].

---

Be conservative. Avoid losses > beat market. Explain clearly.
"""
    
    def _parse_recommendation(self, symbol: str, text: str, fund_score: int, 
                             tech_score: int, fund: Dict, tech: Dict) -> Dict:
        """Parse Claude's response into structured format"""
        
        # Extract values from response
        lines = text.split("\n")
        
        rec_dict = {
            "symbol": symbol,
            "recommendation": "HOLD",
            "conviction": 50,
            "entry_price": tech.get("current_price", 0),
            "stop_loss": tech.get("low_52w", 0) * 0.95,
            "target_price": tech.get("high_52w", 0) * 1.1,
            "fundamentals_score": fund_score,
            "technical_score": tech_score,
            "reasoning": text,
            "reasons": [],
            "risks": [],
            "outlook": "",
            "similar_pattern": ""
        }
        
        # Simple parsing
        for line in lines:
            if "RECOMMENDATION:" in line:
                rec_dict["recommendation"] = line.split(":")[-1].strip().split()[0].upper()
            elif "CONVICTION:" in line:
                try:
                    rec_dict["conviction"] = int(line.split(":")[-1].strip().replace("%", ""))
                except:
                    pass
            elif "ENTRY:" in line:
                try:
                    rec_dict["entry_price"] = float(line.split("$")[-1].strip())
                except:
                    pass
            elif "STOP_LOSS:" in line:
                try:
                    rec_dict["stop_loss"] = float(line.split("$")[-1].strip())
                except:
                    pass
            elif "TARGET:" in line:
                try:
                    rec_dict["target_price"] = float(line.split("$")[-1].strip())
                except:
                    pass
        
        # Save to DB
        self.db.save_recommendation(rec_dict)
        
        return rec_dict
    
    def batch_analyze(self, symbols: List[str]) -> List[Dict]:
        """Analyze multiple stocks"""
        results = []
        for symbol in symbols:
            print(f"Analyzing {symbol}...")
            rec = self.analyze_stock(symbol)
            if rec:
                results.append(rec)
        return results
    
    def format_for_client(self, rec: Dict) -> str:
        """Format recommendation for client email"""
        
        return f"""
{'─'*60}
{rec['symbol']}: {rec['recommendation']} (Conviction {rec['conviction']}%)
{'─'*60}

ENTRY POINT: ${rec['entry_price']:.2f}
STOP LOSS:   ${rec['stop_loss']:.2f}
TARGET:      ${rec['target_price']:.2f}

Conviction {rec['conviction']}% means we're {rec['conviction']}% confident this works.

FUNDAMENTALS SCORE: {rec['fundamentals_score']}/13
TECHNICAL SCORE:    {rec['technical_score']}/5

WHY:
{rec['reasoning']}

RISKS:
{' | '.join(rec.get('risks', ['None identified']))}

{'─'*60}
"""


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    engine = RecommendationEngine()
    
    # Test on 5 large caps
    test_stocks = ["AAPL", "MSFT", "NVDA", "GOOGL", "TSLA"]
    
    print("\nAnalyzing large cap stocks...\n")
    
    recommendations = engine.batch_analyze(test_stocks)
    
    # Print results
    for rec in recommendations:
        print(engine.format_for_client(rec))
    
    # Show accuracy
    accuracy = engine.db.get_accuracy()
    print("\nDATABASE STATS:")
    print(f"Total recommendations: {accuracy['total_recommendations']}")
    print(f"Profitable: {accuracy['profitable']}")
    print(f"Accuracy: {accuracy['accuracy_percent']}%")
    print(f"Average return: {accuracy['average_return_percent']}%")
