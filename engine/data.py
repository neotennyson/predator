from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

ET = "America/New_York"


def _normalize(df: pd.DataFrame, tz: str = ET) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.title)
    keep = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df[keep].dropna(subset=["Close"])
    if len(df) and getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_convert(tz)
    return df


def _cached(path: Path):
    if path.exists():
        try:
            return pd.read_pickle(path)
        except Exception:
            return None
    return None


def get_intraday(symbol: str, day: date, interval: str = "5m", tz: str = ET) -> pd.DataFrame | None:
    path = CACHE_DIR / f"{symbol}_{day.isoformat()}_{interval}.pkl"
    cached = _cached(path)
    if cached is not None:
        return cached if len(cached) else None
    try:
        raw = yf.download(
            symbol,
            start=day.isoformat(),
            end=(day + timedelta(days=1)).isoformat(),
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        return None
    df = _normalize(raw, tz)
    try:
        df.to_pickle(path)
    except Exception:
        pass
    return df if len(df) else None


def get_daily(symbol: str, start: date, end: date) -> pd.DataFrame | None:
    path = CACHE_DIR / f"{symbol}_daily_{start}_{end}.pkl"
    cached = _cached(path)
    if cached is not None:
        return cached if len(cached) else None
    try:
        raw = yf.download(symbol, start=start.isoformat(), end=end.isoformat(), interval="1d", progress=False, auto_adjust=True)
    except Exception:
        return None
    df = _normalize(raw)
    try:
        df.to_pickle(path)
    except Exception:
        pass
    return df if len(df) else None


def get_prev_vix(day: date, symbol: str = "^VIX") -> float | None:
    start = day - timedelta(days=10)
    end = day
    path = CACHE_DIR / f"vix_prev_{symbol.replace('^', '')}_{day.isoformat()}.pkl"
    cached = _cached(path)
    if cached is not None:
        return float(cached) if cached else None
    try:
        raw = yf.download(symbol, start=start.isoformat(), end=end.isoformat(), interval="1d", progress=False, auto_adjust=True)
    except Exception:
        return None
    df = _normalize(raw)
    if not len(df):
        return None
    value = float(df["Close"].iloc[-1])
    try:
        pd.to_pickle(value, path)
    except Exception:
        pass
    return value


def today_intraday(symbol: str, interval: str = "5m", tz: str = ET) -> pd.DataFrame | None:
    try:
        raw = yf.download(symbol, period="1d", interval=interval, progress=False, auto_adjust=True)
    except Exception:
        return None
    return _normalize(raw, tz)
