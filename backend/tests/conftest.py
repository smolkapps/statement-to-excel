"""Shared fixtures. Regenerates the synthetic PDFs once per session if missing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIX = Path(__file__).resolve().parent / "fixtures"


def _ensure_fixtures():
    needed = [
        "acmebank.pdf",
        "columnarcredit.pdf",
        "minimalchecking.pdf",
        "scanned_empty.pdf",
    ]
    if not all((FIX / n).exists() for n in needed):
        from tests.make_fixtures import main as build

        build()


@pytest.fixture(scope="session", autouse=True)
def fixtures_built():
    _ensure_fixtures()
    return FIX


@pytest.fixture
def fixtures_dir() -> Path:
    return FIX


@pytest.fixture
def configured_provider(monkeypatch):
    """Opt into metering explicitly; these synthetic values never contact Stripe."""
    import statement_to_excel.api as api
    from statement_to_excel.billing import StripeBillingProvider

    provider = StripeBillingProvider(
        secret_key="sk_test_synthetic_not_a_credential",
        webhook_secret="whsec_synthetic_not_a_credential",
        portal_configuration="bpc_synthetic",
    )
    monkeypatch.setattr(api, "PROVIDER", provider)
    return provider


def load_expected(name: str):
    return json.loads((FIX / f"{name}.expected.json").read_text())
