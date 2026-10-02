from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app

pytestmark = pytest.mark.integration

DAY = date(2026, 10, 1)
# Real EnergyZero prices for 2026-10-01 (00:00..23:00 Amsterdam), checked by hand in Phase 4.
PRICES_2026_10_01 = (
    "0.155292 0.162768 0.160903 0.162445 0.160087 0.168840 0.203578 0.232442 "
    "0.235533 0.216232 0.197498 0.164355 0.160173 0.158580 0.158160 0.158778 "
    "0.189183 0.232028 0.274690 0.300543 0.257513 0.226397 0.204997 0.186428"
).split()


@pytest.fixture
def client(db_session, make_points):
    db_session.add_all(make_points(DAY, PRICES_2026_10_01))
    db_session.add_all(make_points(date(2025, 10, 26), ["0.1"] * 25))
    db_session.flush()
    app.dependency_overrides[get_session] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_prices(client):
    r = client.get("/api/v1/prices", params={"date": "2026-10-01"})

    assert r.status_code == 200
    body = r.json()
    assert (body["date"], body["source"], len(body["prices"])) == ("2026-10-01", "energyzero", 24)
    assert body["prices"][0] == {
        "start": "2026-10-01T00:00:00+02:00",
        "end": "2026-10-01T01:00:00+02:00",
        "price_eur_per_kwh": "0.1552920000",
        "includes_vat": False,
    }
    assert body["prices"][-1]["end"] == "2026-10-02T00:00:00+02:00"


def test_prices_on_dst_end_show_both_0200_hours(client):
    body = client.get("/api/v1/prices", params={"date": "2025-10-26"}).json()

    starts = [p["start"] for p in body["prices"]]
    assert len(starts) == 25
    assert starts[2:4] == ["2025-10-26T02:00:00+02:00", "2025-10-26T02:00:00+01:00"]


def test_stats(client):
    r = client.get("/api/v1/prices/stats", params={"date": "2026-10-01"})

    assert r.status_code == 200
    assert r.json() == {
        "date": "2026-10-01",
        "source": "energyzero",
        "count": 24,
        "expected_count": 24,
        "is_complete": True,
        "min_price_eur_per_kwh": "0.1552920000",
        "min_price_start": "2026-10-01T00:00:00+02:00",
        "max_price_eur_per_kwh": "0.3005430000",
        "max_price_start": "2026-10-01T19:00:00+02:00",
        "average_price_eur_per_kwh": "0.1969767917",  # 4.727443 / 24
    }


def test_cheapest(client):
    r = client.get("/api/v1/prices/cheapest", params={"date": "2026-10-01", "hours": 3})

    assert r.status_code == 200
    body = r.json()
    assert body["start"] == "2026-10-01T13:00:00+02:00"
    assert body["end"] == "2026-10-01T16:00:00+02:00"
    assert body["average_price_eur_per_kwh"] == "0.1585060000"
    assert [p["price_eur_per_kwh"] for p in body["prices"]] == [
        "0.1585800000",
        "0.1581600000",
        "0.1587780000",
    ]


@pytest.mark.parametrize(
    "path", ["/api/v1/prices", "/api/v1/prices/stats", "/api/v1/prices/cheapest"]
)
def test_missing_date_is_404(client, path):
    r = client.get(path, params={"date": "2026-12-01"})

    assert r.status_code == 404
    assert r.json() == {"detail": "No price data for 2026-12-01 (source: energyzero)"}


def test_window_longer_than_data_is_404(client, db_session, make_points):
    db_session.add_all(make_points(date(2026, 10, 2), ["0.1", "0.1"]))
    db_session.flush()

    r = client.get("/api/v1/prices/cheapest", params={"date": "2026-10-02", "hours": 3})

    assert r.status_code == 404
    assert "longest run of consecutive price data for 2026-10-02 is 2 hours" in r.json()["detail"]


@pytest.mark.parametrize("hours", [0, 13])
def test_hours_out_of_range_is_422(client, hours):
    r = client.get("/api/v1/prices/cheapest", params={"date": "2026-10-01", "hours": hours})

    assert r.status_code == 422


def test_health(client):
    r = client.get("/health")

    assert (r.status_code, r.json()) == (200, {"status": "ok"})


def test_ready(client):
    r = client.get("/ready")

    assert (r.status_code, r.json()) == (200, {"status": "ready"})
