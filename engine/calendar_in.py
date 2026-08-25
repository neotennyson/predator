from datetime import date, timedelta

from .calendar import Catalyst

RELEASE_MPC = "10:00"
RELEASE_BUDGET = "11:00"
RELEASE_SESSION_OPEN = "09:15"

MPC_DECISIONS = {
    2022: ["02-10", "04-08", "06-08", "08-05", "09-30", "12-07"],
    2023: ["02-08", "04-06", "06-08", "08-10", "10-06", "12-08"],
    2024: ["02-08", "04-05", "06-07", "08-08", "10-09", "12-06"],
    2025: ["02-07", "04-09", "06-06", "08-06", "10-01", "12-04"],
    2026: ["02-06", "04-08", "06-05", "08-05", "10-07", "12-04"],
}

ELECTION_RESULT_DAYS = {
    "LS_RESULTS": [date(2024, 6, 4)],
}

EXTRA_CSV_IN = None


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def monthly_expiries(start: date, end: date, weekday: int = 1) -> list[date]:
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        d = _last_weekday_of_month(y, m, weekday)
        if start <= d <= end:
            out.append(d)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _next_weekday(d: date) -> date:
    nd = d + timedelta(days=1)
    while nd.weekday() >= 5:
        nd += timedelta(days=1)
    return nd


def us_gap_events(us_catalysts: list[Catalyst]) -> list[Catalyst]:
    return [Catalyst(_next_weekday(c.day), f"US-{c.name}-GAP", RELEASE_SESSION_OPEN) for c in us_catalysts]


def indian_events(
    start: date,
    end: date,
    include_mpc: bool = True,
    include_budget: bool = True,
    include_elections: bool = True,
    include_monthly_expiry: bool = True,
    include_us_gaps: bool = True,
    us_catalysts: list[Catalyst] | None = None,
    expiry_weekday: int = 1,
) -> list[Catalyst]:
    merged: dict[date, Catalyst] = {}
    if include_monthly_expiry:
        for d in monthly_expiries(start, end, expiry_weekday):
            merged[d] = Catalyst(d, "FNO-EXPIRY", RELEASE_SESSION_OPEN)
    if include_budget:
        for year in range(start.year, end.year + 2):
            merged[date(year, 2, 1)] = Catalyst(date(year, 2, 1), "BUDGET", RELEASE_BUDGET)
    if include_elections:
        for name, days in ELECTION_RESULT_DAYS.items():
            for d in days:
                merged[d] = Catalyst(d, name, RELEASE_SESSION_OPEN)
    if include_mpc:
        for year, months in MPC_DECISIONS.items():
            for md in months:
                d = date.fromisoformat(f"{year}-{md}")
                merged[d] = Catalyst(d, "RBI-MPC", RELEASE_MPC)
    if include_us_gaps and us_catalysts:
        for c in us_gap_events(us_catalysts):
            merged.setdefault(c.day, c)
    return sorted([c for c in merged.values() if start <= c.day <= end], key=lambda c: c.day)


MARKET_PROFILES = {
    "US": {
        "tz": "America/New_York",
        "session_start": "09:30",
        "force_close": "15:55",
        "session_end": "16:00",
        "symbol": "SPY",
        "vix_symbol": "^VIX",
    },
    "IN": {
        "tz": "Asia/Kolkata",
        "session_start": "09:15",
        "force_close": "15:20",
        "session_end": "15:30",
        "symbol": "^NSEI",
        "vix_symbol": "^INDIAVIX",
    },
}
