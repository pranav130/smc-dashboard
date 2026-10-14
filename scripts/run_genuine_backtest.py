"""
Genuine Historical Backtest Execution Script.
Fetches authentic exchange candles directly from Delta Exchange India REST API,
executes the frozen BacktestEngine with chronological walk-forward splits,
and exports the actual generated trade ledger.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.adapters.delta_exchange import DeltaExchangeAdapter
from backend.backtesting.engine import BacktestEngine
from backend.config import STRATEGY_VERSION

async def run_genuine_backtest():
    adapter = DeltaExchangeAdapter()
    print("1. Fetching genuine historical candles from Delta Exchange India (/v2/history/candles)...")
    
    candles_1h = await adapter.fetch_historical_candles("XAUTUSD", "1H", limit=5000)
    candles_4h = await adapter.fetch_historical_candles("XAUTUSD", "4H", limit=1500)
    candles_1d = await adapter.fetch_historical_candles("XAUTUSD", "1D", limit=500)
    
    if not candles_1h:
        print("ERROR: Failed to fetch 1H candles from Delta Exchange India.")
        sys.exit(1)
        
    print(f"   [1H]  Count: {len(candles_1h)} bars ({candles_1h[0].utc_time} to {candles_1h[-1].utc_time})")
    print(f"   [4H]  Count: {len(candles_4h)} bars ({candles_4h[0].utc_time} to {candles_4h[-1].utc_time})")
    print(f"   [1D]  Count: {len(candles_1d)} bars ({candles_1d[0].utc_time} to {candles_1d[-1].utc_time})")
    
    # Save the authentic candle dataset to disk for full provenance and auditability
    os.makedirs("data", exist_ok=True)
    with open("data/genuine_xautusd_1h_candles.json", "w") as f:
        json.dump([c.__dict__ for c in candles_1h], f, indent=2)
    print("   Saved authentic 1H candles to data/genuine_xautusd_1h_candles.json")
    
    engine = BacktestEngine(starting_equity=10000.0)
    print(f"\n2. Executing frozen strategy backtest (Version: {STRATEGY_VERSION})...")
    
    # Run full walk forward validation: 60% Train, 20% Validation, 20% Out-of-Sample Test
    results = engine.run_walk_forward_validation(
        candles_1h=candles_1h,
        candles_4h=candles_4h,
        candles_1d=candles_1d,
        strategy_mode="COMBINED"
    )
    
    # Save genuine results and trade ledgers
    with open("data/genuine_backtest_results.json", "w") as f:
        json.dump(results, f, indent=2)
        
    print("\n3. Genuine Walk-Forward Split Results:")
    splits = results.get("splits", {})
    for split_key, split_data in splits.items():
        print(f"\n--- Split: {split_key} ({split_data.get('split')}) ---")
        print(f"  Total Trades:     {split_data.get('total_trades')}")
        print(f"  Winning Trades:   {split_data.get('winning_trades')}")
        print(f"  Losing Trades:    {split_data.get('losing_trades')}")
        print(f"  Win Rate:         {split_data.get('win_rate_pct')}%")
        print(f"  Gross Profit:     ${split_data.get('gross_profit')}")
        print(f"  Gross Loss:       ${split_data.get('gross_loss')}")
        print(f"  Total Fees:       ${split_data.get('total_fees')}")
        print(f"  Net Profit:       ${split_data.get('net_profit')}")
        print(f"  Profit Factor:    {split_data.get('profit_factor')}")
        print(f"  Expectancy (USD): ${split_data.get('expectancy_dollars')}")
        print(f"  Max Drawdown:     ${split_data.get('max_drawdown_dollars')} ({split_data.get('max_drawdown_pct')}%)")
        print(f"  Sharpe Ratio:     {split_data.get('sharpe_ratio')}")
        print(f"  Sortino Ratio:    {split_data.get('sortino_ratio')}")
        print(f"  Ending Equity:    ${split_data.get('ending_equity')}")
        print(f"  Regime Breakdown: {json.dumps(split_data.get('regime_breakdown', {}), indent=4)}")

    # Also run the full contiguous backtest across ALL genuine candles
    full_run = engine.run_backtest(
        candles_1h=candles_1h,
        candles_4h=candles_4h,
        candles_1d=candles_1d,
        strategy_mode="COMBINED",
        split_name="ALL_GENUINE_HISTORY"
    )
    with open("data/genuine_full_backtest_ledger.json", "w") as f:
        json.dump(full_run, f, indent=2)
        
    print(f"\n--- Full Contiguous Dataset ({len(candles_1h)} candles) ---")
    print(f"  Total Trades:     {full_run.get('total_trades')}")
    print(f"  Win Rate:         {full_run.get('win_rate_pct')}%")
    print(f"  Net Profit:       ${full_run.get('net_profit')}")
    print(f"  Profit Factor:    {full_run.get('profit_factor')}")
    print(f"  Expectancy (USD): ${full_run.get('expectancy_dollars')}")
    print(f"  Max Drawdown:     {full_run.get('max_drawdown_pct')}%")

if __name__ == "__main__":
    asyncio.run(run_genuine_backtest())
