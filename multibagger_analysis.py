import os
from recommendation_engine import RecommendationEngine

def run_multibagger_analysis():
    engine = RecommendationEngine()
    
    # Potential multibagger candidates (High growth, disruptive tech, mid/small caps)
    symbols = ["ASTS", "RKLB", "SOFI", "IOT", "PLTR"]
    
    print("--- MULTI-BAGGER POTENTIAL ANALYSIS ---")
    
    for sym in symbols:
        print(f"\nAnalyzing {sym}...")
        rec = engine.analyze_stock(sym)
        if rec:
            print(f"Recommendation: {rec['recommendation']} | Conviction: {rec['conviction']}%")
            print(f"Entry: ${rec.get('entry_price', 0):.2f} | Target: ${rec.get('target_price', 0):.2f}")
            print(f"Fund Score: {rec.get('fundamentals_score')}/13 | Tech Score: {rec.get('technical_score')}/5")
            
            # Print just the first few sentences or the outlook depending on format
            reasoning = rec['reasoning']
            if "REASONS" in reasoning:
                outlook = reasoning.split("REASONS")[0].strip()
                print(f"Reasoning:\n{outlook}")
            else:
                print(f"Reasoning:\n{reasoning[:500]}...")
        else:
            print(f"Failed to analyze {sym}")
        print("-" * 60)

if __name__ == "__main__":
    run_multibagger_analysis()
