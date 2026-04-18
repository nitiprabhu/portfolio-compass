# 90-DAY IMPLEMENTATION ROADMAP
## "Portfolio Compass" - Stock Recommendation SaaS

---

## THE PRODUCT (Simple Version)

Your customers get:

```
Every Monday:
├─ 5-10 stock recommendations
├─ BUY/SELL/HOLD with conviction score
├─ Entry price + Stop Loss + Target price
├─ 3-5 reasons (fundamentals + technical)
├─ Risk assessment (what could go wrong?)
└─ Email + Dashboard access

Every Month:
├─ Strategy call (30 min)
├─ Portfolio review
├─ Rebalancing suggestions
└─ Accuracy tracking
```

**Price: $2,000/month** for professional segment
**Customer: Busy professional with $500K-$2M portfolio**

---

## WEEK-BY-WEEK ROADMAP

### WEEK 1: Foundation (Jan 15-19)

#### Task 1: Finalize Screening Rules for US Large Caps
```
Current rules (you've tested):
✓ ROE > 15%
✓ Debt/Equity < 1.0
✓ PEG < 1.0
✓ P/E < 25
✓ Revenue growth > 15%
✓ Earnings growth > 10%
✓ Profit margin > 10%
✓ Insider ownership > 5%
✓ Price discount from 52w high
✓ Positive momentum
✓ Volatility < 60%
✓ Market cap > $1B
✓ Free cash flow positive

Action: Score these rules on stocks you KNOW worked:
- NVDA (knew it would go up): What score did it get?
- AAPL (stable): What score?
- TSLA (volatile): What score?

Goal: Rules should correlate with actual future returns
```

#### Task 2: Define Technical Indicators
```
Keep it SIMPLE. Just 5:

1. RSI (Overbought/oversold?)
   - < 30 = Oversold (good buy)
   - > 70 = Overbought (avoid)
   
2. SMA Crossover (trend confirmation)
   - Price > 50-day MA = Uptrend (good)
   - Price > 200-day MA = Long-term up (good)
   
3. Bollinger Bands (volatility zones)
   - Price near lower band = Opportunity
   - Price near upper band = Caution
   
4. MACD (momentum)
   - Positive MACD = Momentum (good)
   - Negative MACD = Momentum down (caution)
   
5. Volatility (risk measure)
   - < 30% annual = Safe
   - 30-60% = Normal
   - > 60% = Risky

Action: Code these 5 indicators in your agent
```

#### Task 3: Create Claude Prompt
```python
# Save this as "recommendation_prompt.txt"

You are a professional investment advisor analyzing stocks for busy professionals.

RULES:
1. Be conservative (avoid losses > beat market)
2. Explain clearly (no jargon)
3. Give specific entry/exit prices
4. Always include downsides
5. Conviction 0-100% (be honest about uncertainty)

ANALYSIS FRAMEWORK:
1. Fundamentals check (apply 13 rules, score 0-13)
2. Technical check (apply 5 indicators, score 0-5)
3. Risk check (what could go wrong?)
4. Timing check (now vs 6 months from now?)
5. Decision (BUY/SELL/HOLD + conviction)

OUTPUT FORMAT:
RECOMMENDATION: [BUY/SELL/HOLD]
Conviction: [0-100]%
Entry Price: $XXX
Stop Loss: $XXX
Target Price: $XXX (12-month)

FUNDAMENTALS:
Score: X/13
Key Strengths: (top 3)
Key Weaknesses: (top 2)

TECHNICAL:
Score: X/5
Momentum: [Strong/Neutral/Weak]
Trend: [Up/Neutral/Down]
Timing: [Good/Okay/Wait]

RISKS:
1. [Risk]
2. [Risk]

SUMMARY:
[2-3 sentences explaining the recommendation]

SIMILAR PATTERNS:
"This is similar to [Stock] in [Month/Year] because [Reason].
That worked out with [Outcome]."
```

### WEEK 2: MVP Build (Jan 22-26)

#### Task 1: Refactor stock_agent.py
```
Current: Analyzes one stock at a time
Needed: 
  ├─ Batch mode (analyze 20 stocks)
  ├─ Return structured JSON (not just text)
  └─ Track outcomes over time

Changes:
1. Add output standardization
   {
     "symbol": "AAPL",
     "recommendation": "BUY",
     "conviction": 72,
     "entry": 150,
     "stop_loss": 130,
     "target": 180,
     "fundamentals_score": 11,
     "technical_score": 4,
     "reasons": ["Strong ROE", "Uptrend", "Undervalued"],
     "risks": ["Valuation", "Market correction"],
     "timestamp": "2024-01-22"
   }

2. Add batch analysis
   symbols = ["AAPL", "MSFT", "NVDA", "TSLA", "GOOGL"]
   results = batch_analyze(symbols)

3. Add database storage (SQLite)
   - Store all recommendations
   - Track actual prices (update daily)
   - Calculate accuracy
```

#### Task 2: Build Simple Dashboard
```
Don't overthink. Just:

Homepage:
├─ Last 5 recommendations
├─ Accuracy (% profitable)
├─ Best/worst performers
└─ Net gain/loss YTD

Recommendation detail page:
├─ Full recommendation + reasoning
├─ Current price vs entry/target
├─ Chart (price history)
├─ Status (Open/Hit Target/Hit Stop Loss)
└─ What we got right/wrong

Portfolio tracker:
├─ Upload CSV of holdings
├─ See recommendation for each
├─ Portfolio status
└─ Alerts (hit stop loss, hit target)

Tech: Simple React + FastAPI endpoint
```

### WEEK 3: Validation (Jan 29-Feb 2)

#### Task 1: Backtest Last 52 Weeks
```
Run agent on 20 large-cap stocks (AAPL, MSFT, NVDA, TSLA, 
GOOGL, AMZN, NFLX, AVGO, MU, COIN, CRWD, DDOG, DECK, 
UPST, SNOW, OKTA, CRM, ADBE, SHOP, CDNS)

For each stock:
1. Run analysis (as of 52 weeks ago)
2. Get recommendation + entry/target/stop
3. Track actual price movement
4. Score: Did it work?

Calculate:
- % of BUY signals profitable (target 55%+)
- % of SELL signals avoided losses (target 60%+)
- Average return on BUY trades
- Average loss avoided on SELL trades
- Risk/reward ratio (target 1:2)

Goal: Prove to yourself it works before selling
```

#### Task 2: Create Sales/Pitch Deck
```
Slide 1: The Problem
- 90% of investors underperform market
- Nobody has time to research 10 hours/week
- Emotional decisions ruin returns

Slide 2: The Solution
- AI-powered stock recommendations
- Clear BUY/SELL/HOLD + reasoning
- Risk management built-in

Slide 3: How It Works
- Fundamental analysis (13 rules)
- Technical analysis (timing)
- Risk assessment
- Simple explanation

Slide 4: Results
- [Your backtest results]
- X% accuracy on recommendations
- Y% risk reduction
- Z% annual outperformance

Slide 5: Pricing
- $2,000/month
- 5-10 recommendations/month
- Monthly strategy call
- Dashboard + alerts

Slide 6: Why Us
- Transparent (you see reasoning)
- Risk-focused (avoid losses)
- Systematic (emotion-free)
- Professional (no hype)

Slide 7: Next Steps
- 30-day free trial
- Money-back if not satisfied
- Portfolio review call

Make it simple, data-driven, no BS
```

### WEEK 4: Find Beta Customers (Feb 5-9)

#### Task 1: Identify and Reach Out
```
Target profile:
- Age: 35-60
- Portfolio: $500K-$2M
- Profession: Doctor, lawyer, engineer, manager, retiree
- Profile: Smart but busy, doesn't have time for investing
- Pain point: Frustrated with underperformance, afraid of losses

Where to find:
1. LinkedIn (search: "portfolio" + "investment")
2. Reddit: r/investing, r/stocks (look for wealthy posters)
3. Angel investor groups
4. Alumni networks
5. Personal network (friends, family, referrals)

Outreach message:
---
Hi [Name],

I'm building a stock recommendation service for busy professionals 
like yourself.

Instead of spending 10 hours/week researching, you get 5-10 clear 
recommendations monthly with entry/exit prices.

I've backtested on 52 weeks of data and achieved [X]% accuracy.
Looking to test with 5 beta customers at $1K/month (50% off final price).

Interested in a 30-min call to discuss?

[Your name]
---

Goal: Get 5 YES by Feb 9
```

#### Task 2: Prepare Onboarding Process
```
Customer signs up → What happens?

Day 1:
- Welcome email
- Get dashboard access
- Schedule strategy call

Strategy Call (30 min):
- Their situation (portfolio size, goals, risk tolerance)
- Your approach (fundamentals + technical + risk)
- Expectations (12-14% annual, not 30%)
- Disclaimer (past performance, losses possible)

Week 1:
- Send first 5 recommendations
- Explain each one
- Get feedback ("too conservative?" "take more risk?")

Week 2-4:
- Send recommendations 2x/week
- Track which ones customer acts on
- Adjust approach based on feedback

Month 2:
- Monthly call to review outcomes
- Any adjustments needed?
- Upsell to $2K/month full plan
```

---

## PHASE 2: PRODUCTIZE (WEEK 5-8)

### WEEK 5-6: Build Dashboard (Feb 12-23)

```
Frontend (React):
├─ Recommendation list (symbol, conviction, entry, target)
├─ Recommendation detail (full reasoning)
├─ Portfolio tracker (upload CSV, see alerts)
├─ Accuracy history (% profitable, avg return)
└─ Settings (risk tolerance, sector preferences)

Backend (FastAPI):
├─ /api/recommendations (get all)
├─ /api/recommendations/{symbol} (get one)
├─ /api/portfolio (upload and analyze)
├─ /api/accuracy (performance tracking)
└─ /api/user (profile, preferences)

Database (SQLite):
├─ recommendations table
├─ portfolio_holdings table
├─ user_preferences table
└─ outcomes table (actual prices, did it work?)
```

### WEEK 7-8: Automation (Feb 26-Mar 2)

```
Set up automated weekly recommendations:

Monday 5 AM:
1. Agent analyzes 30 large-cap stocks
2. Selects top 5-10 (highest conviction, best risk/reward)
3. Creates recommendation objects
4. Dashboard updated
5. Email sent to customers

Daily (after market close):
1. Update actual prices
2. Check if any recommendations hit stop loss/target
3. Send alerts if needed
4. Update accuracy metrics

Monthly (1st of month):
1. Performance report (which recommendations worked?)
2. Accuracy rate
3. Strategy adjustments
4. Trigger customer calls
```

---

## PHASE 3: SCALE (WEEK 9-12)

### WEEK 9-10: Launch (Mar 5-16)

```
Current state:
- 5 beta customers at $1,000/month each = $5K MRR
- Working product (automated recommendations)
- Proven backtest results
- Early feedback incorporated

Actions:
1. Increase beta customer pricing to $1,500/month (show appreciation)
2. Open sales to next 10 customers at $2,000/month
3. Build wait-list for future

Sales channels:
1. LinkedIn outreach (2 hrs/day)
2. Email to angel investor networks
3. Blog posts ("Why 90% of investors fail")
4. Referral program (give $500 credit to customers who refer)
```

### WEEK 11-12: Iterate (Mar 19-30)

```
Measure everything:

Customer metrics:
- How many recommendations do they take?
- What % become profitable?
- Are they happy? (NPS score)
- Will they stay for month 2+?

Product metrics:
- Recommendation accuracy (% profitable)
- Conviction vs outcome (correlation?)
- Risk management (did we avoid losses?)
- Customer satisfaction (feedback)

Business metrics:
- MRR (monthly recurring revenue)
- Churn rate (% leaving)
- Customer acquisition cost
- Lifetime value

Optimize:
- If accuracy < 55%, refine rules
- If customers say "too conservative", add growth screen
- If churn > 5%, fix support
- If CAC > $1K, improve marketing message
```

---

## MONTH 4+: SCALE

```
Target: 50 customers by end of month 4
├─ 40 Professional ($2,000/mo) = $80K MRR
├─ 10 Starter ($500/mo) = $5K MRR
└─ Total: $85K MRR

This requires:
- Repeatable sales process
- Customer success function (support)
- Upgraded infrastructure (faster API)
- Better dashboard UI
- Maybe: hire 1 person

Next features (in order):
1. Sell signal alerts (text when to exit)
2. Portfolio diversification check
3. News integration (catalyst-driven)
4. Sector rotation (when to rotate)
5. Options recommendations (covered calls)
```

---

## TECHNICAL STACK (Keep It Simple)

```
Frontend:
- React (Next.js for faster shipping)
- TailwindCSS (fast styling)
- Recharts (charts)

Backend:
- Python FastAPI (fast, modern)
- Claude API (brain of the system)
- yfinance (free stock data)

Database:
- SQLite (start here)
- Upgrade to PostgreSQL at 100+ customers

Deployment:
- Vercel (frontend)
- Render or Railway (backend)
- Both free tier initially
- Cost: ~$50/month for small scale

Monitoring:
- Sentry (error tracking)
- Simple logging (see what Claude is doing)
```

---

## CRITICAL SUCCESS FACTORS

### 1. Recommendation Accuracy
```
Target: 55%+ of recommendations profitable
Test: Backtest before selling
Proof: Show real results to customers
```

### 2. Customer Retention
```
Target: 80%+ stay past month 2
Driver: Does it actually make them money?
Proof: Track client returns vs S&P 500
```

### 3. Clear Value Prop
```
Don't say: "AI recommends stocks"
Do say: "Make 12-14% annually with less risk"

Don't say: "Sophisticated ML algorithms"
Do say: "Based on fundamentals + timing + risk"

Don't say: "Beat market 30%"
Do say: "Consistent 2-3% outperformance"
```

### 4. Risk Management Messaging
```
This is your actual competitive advantage.

Not: "Find winners"
But: "Avoid losers" + "Better timing" = Better returns

Most investors fear losses. You solve that.
```

---

## FINANCIAL PROJECTIONS

### Conservative Case

```
Month 1-3: 5 customers × $1.5K = $7.5K MRR
Month 4-6: 15 customers × $1.8K = $27K MRR  
Month 7-9: 40 customers × $2K = $80K MRR
Month 10-12: 100 customers × $2K = $200K MRR

Year 1 Revenue: ~$300K
Year 1 Costs:
├─ Claude API: ~$5K (cheap)
├─ Infrastructure: ~$2K (servers)
├─ Tools: ~$3K (office, etc)
├─ Your salary: $60K (be lean)
└─ Hiring: $0 (solo)
Total: ~$70K

Year 1 Gross profit: $230K
Year 1 Net profit: ~$150K (if frugal)
```

### Aggressive Case (With Marketing)

```
Month 1-3: 10 customers × $1.5K = $15K MRR
Month 4-6: 30 customers × $2K = $60K MRR
Month 7-9: 80 customers × $2K = $160K MRR
Month 10-12: 200 customers × $2K = $400K MRR

Year 1 Revenue: ~$800K
Year 1 Costs:
├─ Claude API: ~$10K
├─ Infrastructure: ~$10K
├─ Tools: ~$5K
├─ Your salary: $80K
├─ Hiring (2 people): $200K
└─ Marketing: $50K
Total: ~$355K

Year 1 Gross profit: ~$445K
Year 1 Net profit: ~$90K (investing in growth)
```

---

## IMMEDIATE ACTION ITEMS

### Week 1: Foundation (Jan 15-19) [COMPLETED]
- [x] Test screening rules on 20 stocks
- [x] Define 5 technical indicators
- [x] Create Claude prompt
- [x] Backtest on last 52 weeks

### Week 2: MVP Build (Jan 22-26) [COMPLETED]
- [x] Refactor stock_agent.py for batch analysis
- [x] Build MVP dashboard
- [x] Create pitch deck

### Week 3: Validation (Jan 29-Feb 2) [COMPLETED]
- [x] Complete backtest
- [x] Achieve 55%+ accuracy
- [ ] Identify 10 potential beta customers

### Week 4: Multi-Agent Hub (Feb 5-9) [IN PROGRESS]
- [x] Close 5 beta customers at $1K/month
- [x] Deliver first recommendations
- [x] Implement AI Research Assistant PoC (Context-Augmented RAG)
- [ ] Add Vector Store (ChromaDB) for historical transcripts
- [ ] Implement Streaming Responses (SSE) for Research Assistant

---

## ARCHITECTURE OVERVIEW
The "Portfolio Compass" is an **Agentic AI Suite** consisting of:
1. **The Scanner**: Traditional logic filtering for top growth candidates.
2. **The Evaluator**: Claude-powered reasoning for high-conviction buy/sell signals.
3. **The Researcher**: A deep-dive narrative agent specializing in unstructured text analysis.
4. **The Monitor**: Autonomous background task for daily portfolio rebalancing and alerts.

## THE ONE THING

If you do only ONE thing this week:

**Run backtest on 20 stocks for the last 52 weeks.**

If the accuracy is > 55% (better than flipping a coin), you have a business.
If < 55%, you need to fix the rules.

Everything else flows from this.

Don't overthink. Test first.
