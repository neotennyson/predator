from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import csv

CPI_DATES = {
    2022: ["01-12", "02-10", "03-10", "04-12", "05-11", "06-10", "07-13", "08-10", "09-13", "10-13", "11-10", "12-13"],
    2023: ["01-12", "02-14", "03-14", "04-12", "05-10", "06-13", "07-12", "08-10", "09-13", "10-12", "11-14", "12-12"],
    2024: ["01-11", "02-13", "03-12", "04-10", "05-15", "06-12", "07-11", "08-14", "09-11", "10-10", "11-13", "12-11"],
    2025: ["01-15", "02-12", "03-12", "04-10", "05-13", "06-11", "07-15", "08-12", "09-11", "10-15", "11-13", "12-10"],
    2026: ["01-14", "02-11", "03-11", "04-10", "05-13", "06-11", "07-14", "08-12", "09-11", "10-14", "11-12", "12-10"],
}

FOMC_DAYS = {
    2022: ["01-26", "03-16", "05-04", "06-15", "07-27", "09-21", "11-02", "12-14"],
    2023: ["02-01", "03-22", "05-03", "06-14", "07-26", "09-20", "11-01", "12-13"],
    2024: ["01-31", "03-20", "05-01", "06-12", "07-31", "09-18", "11-07", "12-18"],
    2025: ["01-29", "03-19", "05-07", "06-18", "07-30", "09-17", "10-29", "12-10"],
    2026: ["01-28", "03-18", "04-29", "06-17", "07-29", "09-16", "10-28", "12-09"],
}

EXTRA_CSV = Path(__file__).resolve().parent.parent / "catalysts_extra.csv"


@dataclass(frozen=True)
class Catalyst:
    day: date
    name: str
    release_hhmm: str

    @property
    def label(self) -> str:
        return f"{self.day.isoformat()} {self.name}"


def _build() -> list[Catalyst]:
    seen: dict[date, Catalyst] = {}
    for year, months in CPI_DATES.items():
        for md in months:
            d = date.fromisoformat(f"{year}-{md}")
            seen[d] = Catalyst(d, "CPI", "08:30")
    for year, months in FOMC_DAYS.items():
        for md in months:
            d = date.fromisoformat(f"{year}-{md}")
            if d in seen:
                seen[d] = Catalyst(d, "CPI+FOMC", "08:30")
            else:
                seen[d] = Catalyst(d, "FOMC", "14:00")
    if EXTRA_CSV.exists():
        with open(EXTRA_CSV, newline="") as fh:
            for row in csv.DictReader(fh):
                d = date.fromisoformat(row["date"])
                seen[d] = Catalyst(d, row["name"], row["time"])
    return sorted(seen.values(), key=lambda c: c.day)


ALL: list[Catalyst] = _build()


def catalysts_between(start: date, end: date) -> list[Catalyst]:
    return [c for c in ALL if start <= c.day <= end]


def catalyst_on(day: date) -> Catalyst | None:
    for c in ALL:
        if c.day == day:
            return c
    return None


def upcoming(after: date, n: int = 5) -> list[Catalyst]:
    return [c for c in ALL if c.day > after][:n]
