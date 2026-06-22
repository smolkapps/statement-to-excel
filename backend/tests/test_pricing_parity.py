"""The frontend ships a static pricing.json so it can quote costs before calling
the API. This test asserts that file stays byte-for-value in sync with the
backend billing catalog, so the two never silently drift."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from statement_to_excel.billing import PRICING

FRONTEND_PRICING = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "pricing.json"
)


@pytest.mark.skipif(
    not FRONTEND_PRICING.exists(), reason="frontend/src/pricing.json not present"
)
def test_frontend_pricing_matches_backend():
    fe = json.loads(FRONTEND_PRICING.read_text())

    be_plans = {p["id"]: p for p in PRICING["plans"]}
    fe_plans = {p["id"]: p for p in fe["plans"]}
    assert set(be_plans) == set(fe_plans)
    for pid, be in be_plans.items():
        fp = fe_plans[pid]
        assert int(fp["included_pages"]) == int(be["included_pages"]), pid
        assert Decimal(fp["monthly_price_usd"]) == Decimal(be["monthly_price_usd"]), pid
        assert Decimal(fp["overage_per_page_usd"]) == Decimal(
            be["overage_per_page_usd"]
        ), pid

    be_packs = {c["id"]: c for c in PRICING["credit_packs"]}
    fe_packs = {c["id"]: c for c in fe["credit_packs"]}
    assert set(be_packs) == set(fe_packs)
    for cid, be in be_packs.items():
        fc = fe_packs[cid]
        assert int(fc["credits"]) == int(be["credits"]), cid
        assert Decimal(fc["price_usd"]) == Decimal(be["price_usd"]), cid
        assert Decimal(fc["per_credit_usd"]) == Decimal(be["per_credit_usd"]), cid
