"""FX / multi-currency engine for the Financial Engineering Investment Decision Agent.

Provides:
  - Live exchange-rate fetching (open.er-api.com primary, ECB/Frankfurter backup)
  - SQLite persistence of rate history for audit and re-analysis
  - Manual-rate overrides (clearly marked)
  - Effective-rate resolution with explicit source / timestamp / status
  - Currency conversion helper

Currency codes: USD, ZAR, ZWG (ZiG). Display name 'ZiG'.
Priority when resolving a rate:  Manual override -> Live (session/fresh) -> Stored latest.
An outdated stored rate is never silently used: it is labelled STALE in output.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

CCY_LABELS = {"USD": "USD", "ZAR": "ZAR", "ZWG": "ZiG"}

CURRENCIES = ["USD", "ZAR", "ZWG"]
PAIRS = [
    ("USD", "ZAR"),
    ("ZAR", "USD"),
    ("USD", "ZWG"),
    ("ZWG", "USD"),
    ("ZAR", "ZWG"),
    ("ZWG", "ZAR"),
]
PAIR_LABELS = {f"{a}/{b}": (a, b) for a, b in PAIRS}

_PRIMARY_API = "https://open.er-api.com/v6/latest/USD"
_BACKUP_API_ZAR = "https://open.er-api.com/v6/latest/ZAR"
_ECB_API = "https://api.frankfurter.app/latest"

_HTTP_HEADERS = {"User-Agent": "FinancialInvestmentAgent/1.0"}

STALE_AFTER_SECONDS = 24 * 3600
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fx_rates.db")


@dataclass
class FxRate:
    pair: str
    rate: float
    source: str
    ts: str
    status: str  # LIVE | LIVE (derived) | MANUAL OVERRIDE | STORED | STALE


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _iso_to_epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _http_json(url: str, timeout: int = 8) -> dict[str, Any] | None:
    try:
        req = urllib.request.Request(url, headers=_HTTP_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Live fetching
# ---------------------------------------------------------------------------

def fetch_live_rates(timeout: int = 8) -> dict[str, FxRate]:
    """Fetch the latest rates for all six pairs. Never raises."""
    base: dict[str, float] | None = None
    source = "open.er-api.com"

    payload = _http_json(_PRIMARY_API, timeout)
    if payload and payload.get("result") == "success" and isinstance(payload.get("rates"), dict):
        base = {k.upper(): float(v) for k, v in payload["rates"].items()}

    # Backup: frankfurter (ECB) supplies USD/ZAR only.
    if base is None:
        payload = _http_json(f"{_ECB_API}?from=USD&to=ZAR", timeout)
        if payload and isinstance(payload.get("rates"), dict) and "ZAR" in payload["rates"]:
            base = {"USD": 1.0, "ZAR": float(payload["rates"]["ZAR"])}
            source = "frankfurter.app (ECB)"
        else:
            payload = _http_json(_BACKUP_API_ZAR, timeout)
            if payload and payload.get("result") == "success" and payload.get("base_code") == "ZAR":
                rates = {k.upper(): float(v) for k, v in payload["rates"].items()}
                base = {"USD": rates.get("USD"), "ZAR": 1.0}
                source = "open.er-api.com"

    out: dict[str, FxRate] = {}
    if base and base.get("USD") and base.get("ZAR"):
        usd_zar = base["ZAR"] / base["USD"]
        zwg = base.get("ZWG")
        ts = now_utc()
        out["USD/ZAR"] = FxRate("USD/ZAR", usd_zar, source, ts, "LIVE")
        out["ZAR/USD"] = FxRate("ZAR/USD", 1.0 / usd_zar, f"{source} (derived)", ts, "LIVE (derived)")
        if zwg:
            usd_zwg = zwg / base["USD"]
            out["USD/ZWG"] = FxRate("USD/ZWG", usd_zwg, source, ts, "LIVE")
            out["ZWG/USD"] = FxRate("ZWG/USD", 1.0 / usd_zwg, f"{source} (derived)", ts, "LIVE (derived)")
            out["ZAR/ZWG"] = FxRate("ZAR/ZWG", usd_zar / usd_zwg, f"{source} (derived)", ts, "LIVE (derived)")
            out["ZWG/ZAR"] = FxRate("ZWG/ZAR", usd_zwg / usd_zar, f"{source} (derived)", ts, "LIVE (derived)")
    return out


# ---------------------------------------------------------------------------
# Persistence (SQLite)
# ---------------------------------------------------------------------------

def _connect(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rates_history ("
        "pair TEXT NOT NULL, rate REAL NOT NULL, source TEXT NOT NULL, "
        "status TEXT NOT NULL, ts TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS manual_overrides ("
        "pair TEXT PRIMARY KEY, rate REAL NOT NULL, ts TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def store_live_rates(rates: dict[str, FxRate], db_path: str = DEFAULT_DB) -> int:
    if not rates:
        return 0
    conn = _connect(db_path)
    rows = [
        (r.pair, r.rate, r.source, r.status, r.ts)
        for r in rates.values()
    ]
    conn.executemany(
        "INSERT INTO rates_history (pair, rate, source, status, ts) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def set_manual_override(pair: str, rate: float, db_path: str = DEFAULT_DB) -> None:
    if pair not in PAIR_LABELS:
        raise ValueError(f"Unknown pair: {pair}")
    if rate <= 0:
        raise ValueError("Manual rate must be positive.")
    conn = _connect(db_path)
    conn.execute(
        "INSERT INTO manual_overrides (pair, rate, ts) VALUES (?, ?, ?) "
        "ON CONFLICT(pair) DO UPDATE SET rate=excluded.rate, ts=excluded.ts",
        (pair, rate, now_utc()),
    )
    conn.execute(
        "INSERT INTO rates_history (pair, rate, source, status, ts) VALUES (?, ?, ?, ?, ?)",
        (pair, rate, "Manual Override", "MANUAL OVERRIDE", now_utc()),
    )
    conn.commit()
    conn.close()


def clear_manual_override(pair: str, db_path: str = DEFAULT_DB) -> None:
    conn = _connect(db_path)
    conn.execute("DELETE FROM manual_overrides WHERE pair=?", (pair,))
    conn.commit()
    conn.close()


def get_manual_override(pair: str, db_path: str = DEFAULT_DB) -> float | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT rate FROM manual_overrides WHERE pair=?", (pair,)
    ).fetchone()
    conn.close()
    return float(row[0]) if row else None


def get_stored_latest(pair: str, db_path: str = DEFAULT_DB) -> FxRate | None:
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT rate, source, ts, status FROM rates_history WHERE pair=? "
        "ORDER BY ts DESC LIMIT 1",
        (pair,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return FxRate(pair, float(row[0]), row[1], row[2], row[3])


def get_history(pair: str = None, limit: int = 100, db_path: str = DEFAULT_DB) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    if pair:
        rows = conn.execute(
            "SELECT pair, rate, source, status, ts FROM rates_history "
            "WHERE pair=? ORDER BY ts DESC LIMIT ?",
            (pair, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT pair, rate, source, status, ts FROM rates_history "
            "ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [
        {"pair": p, "rate": r, "source": s, "status": st, "ts": t}
        for p, r, s, st, t in rows
    ]


# ---------------------------------------------------------------------------
# Effective rate resolution
# ---------------------------------------------------------------------------

def resolve_effective_rate(
    pair: str,
    session_live: dict[str, FxRate] | None = None,
    db_path: str = DEFAULT_DB,
) -> FxRate:
    """Resolve the best rate for a pair.

    Priority: manual override -> live (session) -> stored latest.
    A stored rate older than STALE_AFTER_SECONDS is labelled STALE.
    """
    override = get_manual_override(pair, db_path)
    if override is not None:
        ts = now_utc()
        return FxRate(pair, override, "Manual Override", ts, "MANUAL OVERRIDE")

    live = (session_live or {}).get(pair)
    if live is not None:
        return live

    stored = get_stored_latest(pair, db_path)
    if stored is not None:
        age = now_utc()
        try:
            old = datetime.fromisoformat(stored.ts).timestamp()
            age = datetime.now(timezone.utc).timestamp() - old
        except (TypeError, ValueError):
            age = STALE_AFTER_SECONDS + 1
        if age > STALE_AFTER_SECONDS:
            return FxRate(stored.pair, stored.rate, stored.source, stored.ts, "STALE")
        return FxRate(stored.pair, stored.rate, stored.source, stored.ts, "STORED")

    return FxRate(pair, float("nan"), "Unavailable", now_utc(), "UNAVAILABLE")


def all_effective_rates(
    session_live: dict[str, FxRate] | None = None, db_path: str = DEFAULT_DB
) -> dict[str, FxRate]:
    return {
        p: resolve_effective_rate(p, session_live, db_path)
        for p in [f"{a}/{b}" for a, b in PAIRS]
    }


def rates_available(ratemap: dict[str, FxRate]) -> list[str]:
    return [p for p, r in ratemap.items() if r.status != "UNAVAILABLE" and r.rate == r.rate]


def is_stale(ts: str) -> bool:
    try:
        age = datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(ts).timestamp()
        return age > STALE_AFTER_SECONDS
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert_amount(
    amount: float,
    from_ccy: str,
    to_ccy: str,
    ratemap: dict[str, FxRate],
) -> tuple[float | None, str]:
    """Convert amount from one currency to another.

    Returns (converted_amount, status_text). None when the rate is unavailable.
    """
    if from_ccy == to_ccy:
        return amount, f"{CCY_LABELS.get(from_ccy, from_ccy)} = {CCY_LABELS.get(to_ccy, to_ccy)} (1:1)"

    def _rate(from_c: str, to_c: str) -> float | None:
        direct = ratemap.get(f"{from_c}/{to_c}")
        if direct is not None and direct.rate == direct.rate:
            return direct.rate
        inverse = ratemap.get(f"{to_c}/{from_c}")
        if inverse is not None and inverse.rate == inverse.rate:
            return 1.0 / inverse.rate
        return None

    rate = _rate(from_ccy, to_ccy)
    if rate is None and "USD" not in (from_ccy, to_ccy):
        via_usd = _rate(from_ccy, "USD")
        if via_usd is not None:
            usd_to = _rate("USD", to_ccy)
            if usd_to is not None:
                rate = via_usd * usd_to
    if rate is None:
        return None, f"No rate available for {from_ccy}->{to_ccy}."
    return amount * rate, f"{from_ccy}->{to_ccy} @ {rate:,.6f}"


def convert_inputs_for_comparison(
    project_currency: str,
    comparison_currency: str,
    ratemap: dict[str, FxRate],
    financial: dict[str, float],
) -> tuple[dict[str, float], str]:
    """Convert monetary inputs into the comparison currency.

    `financial` fields: initial_investment, annual_revenues, operating_costs,
    working_capital, terminal_value. Non-monetary inputs pass through unchanged.
    Returns (converted_dict, conversion_note).
    """
    monetary = [
        "initial_investment",
        "annual_revenues",
        "operating_costs",
        "working_capital",
        "terminal_value",
    ]
    out = dict(financial)
    notes = []
    for key in monetary:
        amt = out.get(key, 0.0) or 0.0
        conv, note = convert_amount(amt, project_currency, comparison_currency, ratemap)
        if conv is None:
            return out, f"Conversion failed: {note}"
        out[key] = conv
        notes.append(note)
    return out, " | ".join(notes[:3]) + (" | ..." if len(notes) > 3 else "")


# ---------------------------------------------------------------------------
# Board frame
# ---------------------------------------------------------------------------

def build_board_frame(
    session_live: dict[str, FxRate] | None = None, db_path: str = DEFAULT_DB
) -> "pd.DataFrame":
    import pandas as pd

    rows = []
    for p in [f"{a}/{b}" for a, b in PAIRS]:
        r = resolve_effective_rate(p, session_live, db_path)
        rows.append(
            {
                "Currency Pair": p,
                "Live Rate": None if r.rate != r.rate else r.rate,
                "Source": r.source,
                "Date & Time": r.ts,
                "Status": r.status,
            }
        )
    return pd.DataFrame(rows)


def rates_summary_text(ratemap: dict[str, FxRate]) -> list[str]:
    lines = []
    for p in [f"{a}/{b}" for a, b in PAIRS]:
        r = ratemap.get(p)
        if r is None:
            continue
        rate_txt = f"{r.rate:,.6f}" if r.rate == r.rate else "Unavailable"
        lines.append(f"{p}: {rate_txt} [{r.status}] source={r.source} at {r.ts}")
    return lines


# ---------------------------------------------------------------------------
# Self-test (no network required)
# ---------------------------------------------------------------------------

def selftest_conversion() -> None:
    now = now_utc()
    ratemap = {
        "USD/ZAR": FxRate("USD/ZAR", 18.0, "test", now, "LIVE"),
        "USD/ZWG": FxRate("USD/ZWG", 26.0, "test", now, "LIVE"),
    }
    v, _ = convert_amount(1000, "USD", "ZAR", ratemap)
    assert abs(v - 18000) < 1e-6, v
    v, _ = convert_amount(18000, "ZAR", "USD", ratemap)
    assert abs(v - 1000) < 1e-6, v
    v, _ = convert_amount(1000, "USD", "ZWG", ratemap)
    assert abs(v - 26000) < 1e-6, v
    v, _ = convert_amount(26000, "ZWG", "ZAR", ratemap)  # via USD cross
    assert abs(v - 18000) < 1e-6, v


if __name__ == "__main__":
    selftest_conversion()
    print("fx_rates selftest OK")