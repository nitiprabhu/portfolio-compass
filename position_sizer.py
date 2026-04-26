#!/usr/bin/env python3
"""
POSITION SIZER — Volatility-Adjusted Risk Management
======================================================
Replaces the naïve $10K-per-position approach with institutional-grade sizing:

1. ATR-based sizing (prop-desk standard): risk per trade = 2% of account
2. Volatility targeting (hedge fund standard): equalise each position's vol contribution
3. Correlation guard: reduce size when new position is correlated with existing holdings

The final size is the MINIMUM of methods 1 & 2, further reduced by the correlation guard.
"""

import numpy as np
import yfinance as yf
from typing import Dict, List, Optional


def calculate_position_size(
    account_value: float,
    entry_price: float,
    atr14: float,
    annual_volatility: float = 30.0,
    target_portfolio_vol: float = 15.0,
    max_risk_per_trade: float = 0.02,
    n_positions: int = 5,
    correlation_penalty: float = 1.0
) -> Dict:
    """
    Calculate position size using dual ATR + vol-targeting approach.

    Args:
        account_value: Total portfolio value in dollars
        entry_price: Stock entry price
        atr14: 14-day Average True Range
        annual_volatility: Stock's annualised volatility (%)
        target_portfolio_vol: Target portfolio volatility (%, default 15%)
        max_risk_per_trade: Max fraction of account to risk per trade (default 2%)
        n_positions: Number of portfolio positions (for vol-target allocation)
        correlation_penalty: 0.0 to 1.0 multiplier (1.0 = no penalty, 0.5 = halved)

    Returns:
        Dict with shares, position_value, risk_dollars, pct_of_account, method_used
    """
    if entry_price <= 0 or atr14 <= 0 or account_value <= 0:
        return {
            "shares": 0, "position_value": 0, "risk_dollars": 0,
            "pct_of_account": 0, "method_used": "error"
        }

    # ── Method 1: ATR-based risk sizing ──────────────────────────────────
    # Each share risks 2 × ATR on the stop; total risk = max_risk_per_trade × account
    risk_per_share = 2.0 * atr14
    max_risk_dollars = account_value * max_risk_per_trade
    shares_by_risk = max_risk_dollars / risk_per_share

    # ── Method 2: Volatility targeting ───────────────────────────────────
    # Size each position so it contributes equal vol to portfolio
    stock_vol_annual = max(annual_volatility / 100.0, 0.01)
    target_vol = target_portfolio_vol / 100.0
    # Per-position allocation = (target_vol / n_positions) / stock_vol
    per_pos_vol_budget = target_vol / max(n_positions, 1)
    position_dollars_by_vol = (per_pos_vol_budget / stock_vol_annual) * account_value
    shares_by_vol = position_dollars_by_vol / entry_price

    # ── Take the more conservative (smaller) ─────────────────────────────
    if shares_by_risk <= shares_by_vol:
        base_shares = shares_by_risk
        method = "atr_risk"
    else:
        base_shares = shares_by_vol
        method = "vol_target"

    # ── Apply correlation penalty ─────────────────────────────────────────
    final_shares = max(int(base_shares * correlation_penalty), 0)

    # ── Hard cap: never more than 20% of account in one position ─────────
    max_position_value = account_value * 0.20
    max_shares_by_cap = int(max_position_value / entry_price)
    if final_shares > max_shares_by_cap:
        final_shares = max_shares_by_cap
        method += "+capped"

    position_value = round(final_shares * entry_price, 2)
    risk_dollars = round(final_shares * risk_per_share, 2)
    pct_of_account = round(position_value / account_value * 100, 2) if account_value > 0 else 0

    return {
        "shares": final_shares,
        "position_value": position_value,
        "risk_dollars": risk_dollars,
        "pct_of_account": pct_of_account,
        "method_used": method,
        "atr_shares": int(shares_by_risk),
        "vol_shares": int(shares_by_vol),
    }


def calculate_correlation_penalty(
    new_symbol: str,
    existing_symbols: List[str],
    threshold: float = 0.70,
    lookback_days: int = 90
) -> float:
    """
    Check pairwise correlation between new_symbol and existing holdings.

    Returns:
        Penalty multiplier (0.5 if highly correlated, 1.0 if no issue).
    """
    if not existing_symbols:
        return 1.0

    try:
        all_symbols = [new_symbol] + existing_symbols
        data = yf.download(all_symbols, period=f"{lookback_days}d", progress=False)

        if data.empty:
            return 1.0

        # Extract close prices
        if len(all_symbols) > 1:
            closes = data["Close"]
        else:
            closes = data[["Close"]]
            closes.columns = [new_symbol]

        returns = closes.pct_change().dropna()

        if returns.shape[0] < 20:
            return 1.0

        # Get correlations of new_symbol vs all existing
        corr_matrix = returns.corr()
        if new_symbol not in corr_matrix.columns:
            return 1.0

        max_corr = 0.0
        for sym in existing_symbols:
            if sym in corr_matrix.columns:
                pair_corr = abs(corr_matrix.loc[new_symbol, sym])
                max_corr = max(max_corr, pair_corr)

        if max_corr >= threshold:
            # Linearly scale penalty: corr 0.7→1.0 maps to penalty 0.75→0.3
            penalty = max(0.3, 1.0 - (max_corr - threshold) / (1.0 - threshold) * 0.7)
            return round(penalty, 2)

        return 1.0

    except Exception as e:
        print(f"Correlation check error: {e}")
        return 1.0


def get_portfolio_risk_summary(
    positions: List[Dict],
    account_value: float
) -> Dict:
    """
    Calculate portfolio-level risk metrics.

    Args:
        positions: List of dicts with keys: symbol, shares, entry_price, atr14
        account_value: Total portfolio value

    Returns:
        Dict with total_risk, concentration, estimated_portfolio_vol
    """
    if not positions or account_value <= 0:
        return {"total_risk_pct": 0, "largest_position_pct": 0, "estimated_annual_vol_pct": 0}

    total_risk = 0
    position_values = []

    for pos in positions:
        shares = pos.get("shares", 0)
        atr = pos.get("atr14", 0)
        entry = pos.get("entry_price", 0)
        risk = shares * 2.0 * atr
        total_risk += risk
        position_values.append(shares * entry)

    total_risk_pct = round(total_risk / account_value * 100, 2)
    largest_pct = round(max(position_values) / account_value * 100, 2) if position_values else 0

    return {
        "total_risk_pct": total_risk_pct,
        "largest_position_pct": largest_pct,
        "n_positions": len(positions),
        "avg_position_pct": round(sum(position_values) / account_value * 100 / len(positions), 2) if positions else 0,
    }


if __name__ == "__main__":
    # Example usage
    result = calculate_position_size(
        account_value=100_000,
        entry_price=150.0,
        atr14=3.50,
        annual_volatility=25.0,
        n_positions=5
    )
    print("Position Size Result:")
    for k, v in result.items():
        print(f"  {k}: {v}")

    # Correlation check example
    penalty = calculate_correlation_penalty("MSFT", ["AAPL", "GOOGL"])
    print(f"\nCorrelation penalty for MSFT vs [AAPL, GOOGL]: {penalty}")
