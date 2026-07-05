"""Offline tests for Task 9 connectors.

Tests never hit the network: they feed recorded JSON fixtures to the pure
``_parse_*`` functions and assert the typed objects that come back. They also
verify the blinding invariant (``BlindCandidate`` carries no market opinion),
graceful degradation when API keys are absent, and the registry / doctor
surface.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from oracle.connectors import (
    BlindCandidate,
    Connector,
    MarketMatch,
    PricePoint,
    SealedSnapshot,
    doctor,
    registry,
)
from oracle.connectors import manifold, metaculus, polymarket, fred, asknews

FIXTURES = Path(__file__).parent / "fixtures" / "connectors"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


# --------------------------------------------------------------------------- #
# Blinding invariant (§6.6): the type system, not the prompt, enforces it.
# --------------------------------------------------------------------------- #

def test_blind_candidate_carries_no_market_opinion():
    fields = set(BlindCandidate.model_fields)
    for leaked in ("price", "probability", "community", "community_prediction",
                   "comments", "n_forecasters", "liquidity", "volume"):
        assert leaked not in fields, f"BlindCandidate must not expose {leaked!r}"
    assert fields == {
        "platform", "market_id", "title", "resolution_criteria",
        "close_date", "category",
    }


# --------------------------------------------------------------------------- #
# Manifold
# --------------------------------------------------------------------------- #

def test_manifold_parse_search():
    matches = manifold._parse_search(_load("manifold_search.json"))
    assert all(isinstance(m, MarketMatch) for m in matches)
    assert len(matches) == 2
    first = matches[0]
    assert first.platform == "manifold"
    assert first.market_id == "j5f3k2"
    assert first.title == "Will the RBA cut the cash rate in August 2026?"
    assert first.url.startswith("https://manifold.markets/")


def test_manifold_parse_price():
    pp = manifold._parse_price_point(_load("manifold_market.json"))
    assert isinstance(pp, PricePoint)
    assert pp.platform == "manifold"
    assert pp.market_id == "j5f3k2"
    assert pp.price == pytest.approx(0.62)
    assert pp.ts.tzinfo is not None


def test_manifold_parse_candidate_is_blind():
    c = manifold._parse_candidate(_load("manifold_market.json"))
    assert isinstance(c, BlindCandidate)
    assert c.platform == "manifold"
    assert c.market_id == "j5f3k2"
    assert c.category == "economics"
    assert "RBA" in c.resolution_criteria
    expected_close = datetime.fromtimestamp(1786752000000 / 1000, tz=timezone.utc)
    assert c.close_date == expected_close
    # The stripped type has no way to carry the market's opinion.
    assert not hasattr(c, "price")
    assert not hasattr(c, "probability")


def test_manifold_parse_snapshot_keeps_opinion():
    snap = manifold._parse_snapshot(_load("manifold_market.json"))
    assert isinstance(snap, SealedSnapshot)
    assert snap.price == pytest.approx(0.62)
    assert snap.n_forecasters == 47
    assert snap.liquidity == pytest.approx(450.0)
    assert snap.ts.tzinfo is not None


# --------------------------------------------------------------------------- #
# Metaculus
# --------------------------------------------------------------------------- #

def test_metaculus_parse_list():
    matches = metaculus._parse_list(_load("metaculus_list.json"))
    assert all(isinstance(m, MarketMatch) for m in matches)
    assert len(matches) == 2
    assert matches[0].market_id == "30123"
    assert matches[0].platform == "metaculus"
    assert matches[0].url == "https://www.metaculus.com/questions/30123/rba-cash-rate-august-2026/"


def test_metaculus_parse_candidate_is_blind():
    c = metaculus._parse_candidate(_load("metaculus_question.json"))
    assert isinstance(c, BlindCandidate)
    assert c.market_id == "30123"
    assert c.platform == "metaculus"
    assert c.category == "economy"
    assert c.close_date == datetime(2026, 8, 1, 5, 0, tzinfo=timezone.utc)
    assert "Reserve Bank" in c.resolution_criteria


def test_metaculus_parse_snapshot():
    snap = metaculus._parse_snapshot(_load("metaculus_question.json"))
    assert snap.platform == "metaculus"
    assert snap.market_id == "30123"
    assert snap.price == pytest.approx(0.58)
    assert snap.n_forecasters == 85


# --------------------------------------------------------------------------- #
# Polymarket
# --------------------------------------------------------------------------- #

def test_polymarket_parse_list():
    matches = polymarket._parse_list(_load("polymarket_list.json"))
    assert len(matches) == 2
    assert matches[0].platform == "polymarket"
    assert matches[0].market_id == "512038"
    assert "polymarket.com" in matches[0].url


def test_polymarket_parse_price_decodes_string_array():
    pp = polymarket._parse_price_point(_load("polymarket_market.json"))
    assert pp.price == pytest.approx(0.61)
    assert pp.platform == "polymarket"


def test_polymarket_parse_candidate_is_blind():
    c = polymarket._parse_candidate(_load("polymarket_market.json"))
    assert isinstance(c, BlindCandidate)
    assert c.market_id == "512038"
    assert c.category == "Economics"
    assert c.close_date == datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def test_polymarket_parse_snapshot():
    snap = polymarket._parse_snapshot(_load("polymarket_market.json"))
    assert snap.price == pytest.approx(0.61)
    assert snap.liquidity == pytest.approx(18000.75)


# --------------------------------------------------------------------------- #
# FRED
# --------------------------------------------------------------------------- #

def test_fred_parse_observations_skips_missing():
    series = fred._parse_observations(_load("fred_observations.json"))
    assert series == [
        (date(2026, 1, 1), 3.2),
        (date(2026, 3, 1), 3.5),
    ]


def test_fred_available_false_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    conn = fred.FredConnector()
    assert conn.available() is False  # must not raise


# --------------------------------------------------------------------------- #
# AskNews (optional, guarded import)
# --------------------------------------------------------------------------- #

def test_asknews_available_false_without_creds(monkeypatch):
    monkeypatch.delenv("ASKNEWS_CLIENT_ID", raising=False)
    monkeypatch.delenv("ASKNEWS_CLIENT_SECRET", raising=False)
    conn = asknews.AskNewsConnector()
    assert conn.available() is False  # must not raise even if SDK absent


# --------------------------------------------------------------------------- #
# Registry + doctor
# --------------------------------------------------------------------------- #

def test_registry_has_all_connectors():
    reg = registry()
    assert set(reg) == {"manifold", "metaculus", "polymarket", "fred", "asknews"}
    for name, conn in reg.items():
        assert isinstance(conn, Connector)
        assert conn.name == name


def test_free_connectors_are_available_without_keys(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    reg = registry()
    # Manifold/Polymarket need no auth for reads.
    assert reg["manifold"].available() is True
    assert reg["polymarket"].available() is True


def test_metaculus_availability_gated_on_token(monkeypatch):
    # Metaculus now requires an API token even for reads; degrade cleanly without one.
    from oracle.connectors.metaculus import MetaculusConnector

    monkeypatch.delenv("METACULUS_API_TOKEN", raising=False)
    assert MetaculusConnector().available() is False
    monkeypatch.setenv("METACULUS_API_TOKEN", "tok-123")
    conn = MetaculusConnector()
    assert conn.available() is True
    assert conn._headers()["Authorization"] == "Token tok-123"


def test_doctor_reports_without_leaking_secrets(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "super-secret-value-123")
    rows = doctor()
    names = {r[0] for r in rows}
    assert names == {"manifold", "metaculus", "polymarket", "fred", "asknews"}
    for name, available, detail in rows:
        assert isinstance(available, bool)
        assert isinstance(detail, str)
        assert "super-secret-value-123" not in detail
