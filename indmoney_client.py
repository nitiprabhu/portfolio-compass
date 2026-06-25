import os
import json
import httpx
import asyncio
from typing import Dict, List, Optional
from recommendation_engine import RecommendationEngine

class IndMoneyClient:
    def __init__(self, auth_token: Optional[str] = None):
        self.auth_token = auth_token or os.environ.get("INDMONEY_AUTH_TOKEN")
        self.base_url = "https://mcp.indmoney.com/mcp"
        self.engine = RecommendationEngine()

    async def get_holdings(self) -> List[Dict]:
        """
        Connect to the INDmoney MCP SSE server and invoke holdings retrieval.
        Falls back to mock holdings if no auth token is provided.
        """
        if not self.auth_token:
            print("⚠️ No INDMONEY_AUTH_TOKEN found. Returning mock portfolio data.")
            return [
                {"symbol": "PLTR", "shares": 100, "entry_price": 32.50, "type": "US Stock"},
                {"symbol": "SOFI", "shares": 500, "entry_price": 9.20, "type": "US Stock"},
                {"symbol": "GOOGL", "shares": 15, "entry_price": 165.00, "type": "US Stock"},
                {"symbol": "INFY", "shares": 50, "entry_price": 22.10, "type": "Indian Stock"}
            ]

        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json"
        }

        try:
            # 1. Establish SSE Connection and get messaging endpoint
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Typically SSE starts with a GET request
                r = await client.get(self.base_url, headers=headers)
                if r.status_code != 200:
                    raise Exception(f"Failed to connect to IndMoney MCP server: {r.status_code} {r.text}")

                # If the server redirects or provides direct JSON-RPC endpoint
                # In MCP SSE, the connection endpoint often returns SSE stream with endpoint path.
                # Since we don't have interactive browser here, we try to call tools directly via POST:
                # Standard MCP SSE JSON-RPC POST call
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "get_portfolio_holdings",
                        "arguments": {}
                    }
                }
                
                # Check for alternative tool name common to brokers
                # Post JSON-RPC request to base URL as fallback
                res = await client.post(self.base_url, json=payload, headers=headers)
                if res.status_code == 200:
                    result = res.json()
                    if "result" in result:
                        content = result["result"].get("content", [])
                        if content and len(content) > 0:
                            data = json.loads(content[0].get("text", "[]"))
                            return data

                # Fallback to alternative tools/list call
                list_payload = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {}
                }
                list_res = await client.post(self.base_url, json=list_payload, headers=headers)
                print(f"IndMoney MCP tools list response: {list_res.text}")
                
        except Exception as e:
            print(f"❌ Error fetching holdings from INDmoney MCP: {e}")
            
        # Fallback Mock Data in case of network or authentication issue
        return [
            {"symbol": "PLTR", "shares": 100, "entry_price": 32.50, "type": "US Stock"},
            {"symbol": "SOFI", "shares": 500, "entry_price": 9.20, "type": "US Stock"},
            {"symbol": "GOOGL", "shares": 15, "entry_price": 165.00, "type": "US Stock"}
        ]

    async def generate_portfolio_suggestions(self, holdings: List[Dict]) -> List[Dict]:
        """
        Cross-reference holdings with the recommendation engine to suggest actions.
        """
        suggestions = []
        for hold in holdings:
            symbol = hold["symbol"]
            entry = hold["entry_price"]
            
            # Fetch latest recommendation from db
            rec = self.engine.db.get_last_recommendation(symbol)
            if not rec:
                # If not analyzed recently, run analysis on it
                rec = self.engine.analyze_stock(symbol, bypass_cache=True, save_to_db=True)

            if rec:
                current_price = rec.get("entry_price") or entry
                rec_action = rec.get("recommendation", "HOLD")
                
                # Logic to suggest actions
                pnl_pct = ((current_price - entry) / entry) * 100 if entry else 0
                
                suggested_action = "HOLD"
                if rec_action == "SELL" or rec_action == "AVOID":
                    suggested_action = "SELL (Underperforming / Weak Outlook)"
                elif rec_action in ("BUY", "STRONG BUY") and pnl_pct > 20:
                    suggested_action = "TAKE PARTIAL PROFIT (Up >20%)"
                elif rec_action in ("BUY", "STRONG BUY") and pnl_pct < -10:
                    suggested_action = "ACCUMULATE (Strong conviction, average down)"
                elif rec_action in ("BUY", "STRONG BUY"):
                    suggested_action = "HOLD/BUY MORE"
                
                suggestions.append({
                    "symbol": symbol,
                    "shares": hold["shares"],
                    "entry_price": entry,
                    "current_price": current_price,
                    "pnl_pct": pnl_pct,
                    "compass_recommendation": rec_action,
                    "compass_conviction": rec.get("conviction", 50),
                    "suggested_action": suggested_action,
                    "outlook": rec.get("outlook", "")
                })
        return suggestions
