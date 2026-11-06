from datetime import datetime

import pytest
import requests

import main

UPDATED = "Fri, 06 Nov 2026 00:02:31 +0000"


# ---------- helpers ----------

class FakeResponse:
    """Stands in for requests.Response so tests never touch the network."""

    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        return self._payload


def api_payload(rate=1512.4, updated=UPDATED):
    return {"rates": {"NGN": rate}, "time_last_update_utc": updated}


def fake_network(monkeypatch, outcomes):
    """Replace requests.get with a script of outcomes (responses or exceptions).

    Also replaces time.sleep so retry tests run instantly, and records the
    waits so we can check them.
    """
    calls, waits = [], []
    queue = list(outcomes)

    def fake_get(url, timeout=None):
        calls.append(url)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(main.requests, "get", fake_get)
    monkeypatch.setattr(main.time, "sleep", lambda seconds: waits.append(seconds))
    return calls, waits


@pytest.fixture
def rates_file(tmp_path, monkeypatch):
    """Point the app at a temporary CSV so tests never touch the real one."""
    path = tmp_path / "rates.csv"
    monkeypatch.setattr(main, "RATES_FILE", path)
    return path


# ---------- format_message ----------

def test_format_message_includes_rate_and_time():
    message = main.format_message(1512.4, UPDATED)
    assert "1,512.40" in message
    assert UPDATED in message


def test_format_message_says_unknown_when_time_missing():
    assert "unknown" in main.format_message(1512.4, None)


# ---------- check_thresholds ----------

def test_rate_below_lower_threshold_alerts():
    alert = main.check_thresholds(1300.0, lower=1400.0, upper=1600.0)
    assert alert is not None
    assert "below" in alert


def test_rate_above_upper_threshold_alerts():
    alert = main.check_thresholds(1700.0, lower=1400.0, upper=1600.0)
    assert alert is not None
    assert "above" in alert


@pytest.mark.parametrize("rate", [1400.0, 1500.0, 1600.0])
def test_rate_inside_range_or_on_boundary_does_not_alert(rate):
    assert main.check_thresholds(rate, lower=1400.0, upper=1600.0) is None


# ---------- rate_date ----------

def test_rate_date_same_day_in_lagos():
    assert main.rate_date("Wed, 28 Oct 2026 00:02:31 +0000") == "2026-10-28"


def test_rate_date_rolls_to_next_day_in_lagos():
    # 23:30 UTC is 00:30 the next day in Lagos (UTC+1)
    assert main.rate_date("Wed, 28 Oct 2026 23:30:00 +0000") == "2026-10-29"


@pytest.mark.parametrize("bad_value", [None, "not a date"])
def test_rate_date_falls_back_to_a_valid_date(bad_value):
    result = main.rate_date(bad_value)
    datetime.strptime(result, "%Y-%m-%d")  # raises if the format is wrong


# ---------- save_rate ----------

def test_save_rate_creates_file_with_header_and_row(rates_file):
    assert main.save_rate(1512.4, UPDATED) is True
    assert rates_file.read_text().splitlines() == ["date,rate", "2026-11-06,1512.4"]


def test_save_rate_skips_duplicate_date(rates_file):
    main.save_rate(1512.4, UPDATED)
    assert main.save_rate(1520.0, UPDATED) is False
    assert len(rates_file.read_text().splitlines()) == 2  # header + one row


def test_save_rate_appends_a_new_date(rates_file):
    main.save_rate(1512.4, UPDATED)
    main.save_rate(1500.0, "Sat, 07 Nov 2026 00:02:31 +0000")
    assert rates_file.read_text().splitlines() == [
        "date,rate",
        "2026-11-06,1512.4",
        "2026-11-07,1500.0",
    ]


def test_save_rate_adds_header_to_an_empty_existing_file(rates_file):
    rates_file.touch()
    assert main.save_rate(1512.4, UPDATED) is True
    assert rates_file.read_text().splitlines()[0] == "date,rate"


# ---------- fetch_rate (network mocked) ----------

def test_fetch_rate_returns_rate_and_time(monkeypatch):
    calls, waits = fake_network(monkeypatch, [FakeResponse(200, api_payload())])
    assert main.fetch_rate() == (1512.4, UPDATED)
    assert len(calls) == 1
    assert waits == []


def test_fetch_rate_retries_after_a_connection_error(monkeypatch):
    calls, waits = fake_network(
        monkeypatch, [requests.ConnectionError(), FakeResponse(200, api_payload())]
    )
    assert main.fetch_rate() == (1512.4, UPDATED)
    assert len(calls) == 2
    assert waits == [main.RETRY_WAIT_SECONDS]


def test_fetch_rate_retries_after_a_server_error(monkeypatch):
    calls, _ = fake_network(
        monkeypatch, [FakeResponse(503), FakeResponse(200, api_payload())]
    )
    assert main.fetch_rate() is not None
    assert len(calls) == 2


def test_fetch_rate_does_not_retry_a_404(monkeypatch):
    calls, waits = fake_network(monkeypatch, [FakeResponse(404)])
    assert main.fetch_rate() is None
    assert len(calls) == 1
    assert waits == []


def test_fetch_rate_gives_up_after_max_attempts(monkeypatch):
    outcomes = [requests.Timeout() for _ in range(main.MAX_ATTEMPTS)]
    calls, waits = fake_network(monkeypatch, outcomes)
    assert main.fetch_rate() is None
    assert len(calls) == main.MAX_ATTEMPTS
    assert waits == [main.RETRY_WAIT_SECONDS, main.RETRY_WAIT_SECONDS * 2]


def test_fetch_rate_returns_none_when_ngn_missing(monkeypatch):
    fake_network(monkeypatch, [FakeResponse(200, {"rates": {}})])
    assert main.fetch_rate() is None