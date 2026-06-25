import os
import yfinance as yf
import time
from recommendation_engine import RecommendationEngine
from scanner import MarketScanner

class MultibaggerScreener:
    def __init__(self):
        self.engine = RecommendationEngine()
        self.scanner = MarketScanner()

    def run_screener(self, limit=5) -> list:
        print("🔍 Starting Fundamental Multibagger Screener...")
        
        # 1. Get Small Cap Universe
        tickers = self.scanner.get_small_cap_tickers()
        if not tickers:
            tickers = ["ASTS", "RKLB", "SOFI", "IOT", "PLTR", "UPST", "CELH", "RXRX", "SPHR"]
            print(f"Fallback to growth tickers: {tickers}")
        else:
            print(f"Retrieved {len(tickers)} S&P 600 tickers to screen.")
            
        screened_symbols = []
        
        # Screen in batches to avoid rate limits
        for symbol in tickers[:80]:  # Scan top 80 by volume or just first 80 for demo/performance
            try:
                fund = self.engine._get_fundamentals(symbol)
                if "error" in fund or fund.get("quote_type") != "EQUITY":
                    continue
                
                # Fundamental Criteria
                piotroski = fund.get("piotroski_score", 0)
                roe = fund.get("roe") or 0.0
                debt_equity = fund.get("debt_equity") or 999.0
                revenue_growth = fund.get("revenue_growth") or 0.0
                
                # Check for multibagger characteristics:
                # - Piotroski Score >= 5 (Quality balance sheet)
                # - ROE >= 12% (Capital compounder)
                # - Debt-to-Equity <= 1.0 (Low risk of bankruptcy)
                # - Revenue Growth >= 15% (High growth trajectory)
                if piotroski >= 5 and roe >= 0.12 and debt_equity <= 100.0 and revenue_growth >= 0.15:
                    print(f"  ✨ Winner found: {symbol} (Piotroski={piotroski}, ROE={roe*100:.1f}%, D/E={debt_equity:.1f}, Rev Growth={revenue_growth*100:.1f}%)")
                    screened_symbols.append((symbol, fund))
                    if len(screened_symbols) >= limit:
                        break
            except Exception as e:
                # print(f"Error screening {symbol}: {e}")
                pass
            time.sleep(0.2)
            
        if not screened_symbols:
            print("No new symbols passed all strict criteria. Using top growth fallbacks.")
            fallbacks = ["ASTS", "RKLB", "SOFI"]
            for f in fallbacks:
                try:
                    fund = self.engine._get_fundamentals(f)
                    screened_symbols.append((f, fund))
                except:
                    pass

        # 2. Run AI Deep-Dive with Multibagger Mode (Sonnet Devil's Advocate)
        findings = []
        print(f"\n🧠 Running AI Deep-Dive in MULTIBAGGER mode for {len(screened_symbols)} symbols...")
        for sym, fund in screened_symbols:
            print(f"  Analyzing {sym} with Claude 3.5 Sonnet (Argue-Against)...")
            rec = self.engine.analyze_stock(sym, bypass_cache=True, save_to_db=True, mode="multibagger")
            if rec:
                print(f"  Recommendation: {rec['recommendation']} | Conviction: {rec['conviction']}%")
                findings.append(rec)
            time.sleep(1)
            
        return findings

if __name__ == "__main__":
    screener = MultibaggerScreener()
    results = screener.run_screener(limit=3)
