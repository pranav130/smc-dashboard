import pytest
import asyncio
from backend.adapters.delta_exchange import DeltaExchangeAdapter

@pytest.mark.asyncio
async def test_live_delta_product_verification():
    adapter = DeltaExchangeAdapter()
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{adapter.base_rest_url}/v2/products")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        products = data.get("result", [])
        xaut = next((p for p in products if p.get("symbol") == "XAUTUSD"), None)
        assert xaut is not None, "XAUTUSD must exist on Delta Exchange India"
        assert xaut.get("id") == 131253
        assert xaut.get("contract_type") == "perpetual_futures"
        assert xaut.get("trading_status") == "operational"

@pytest.mark.asyncio
async def test_live_historical_candles_all_timeframes():
    adapter = DeltaExchangeAdapter()
    for tf in ["1D", "4H", "1H", "30M"]:
        candles = await adapter.fetch_historical_candles("XAUTUSD", tf, limit=50)
        assert len(candles) > 0, f"Candles for {tf} should not be empty"
        # Verify chronological order
        for i in range(len(candles) - 1):
            assert candles[i].time < candles[i + 1].time, f"Candles in {tf} must be strictly chronological"
            assert candles[i].high >= candles[i].low
            assert candles[i].high >= candles[i].open
            assert candles[i].high >= candles[i].close
