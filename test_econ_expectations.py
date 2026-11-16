"""
16.11.2026 (пакет 16.11, т. 9): икономическите заглавия в карето в 15:05 — с очакванията (консенсуса) от календара на Nasdaq; без съвпадение — „очаквания: няма данни“;
календарът не се изтегли — „очаквания: не се провериха (…)“. Реално 13.11: „Wholesale prices rose 0.3% in October, putting annual rate at 6.5%, the highest in nearly four years“
(CNBC, 09:02 Ню Йорк) — без „под очакваното: 0.3% срещу 0.4%“.

РЕАЛНО: tests/fixtures/nasdaq_econ_q2026-11-14.json.gz — api.nasdaq.com/api/calendar/economicevents?date=2026-11-14 (събитията на 13.11; изтеглено 16.11.2026); заглавието — от
data/preopen/2026-11-13.json, цитирано тук. СИНТЕТИЧНО (означено): провалът на календара.
Пускане: python test_econ_expectations.py
"""
import sys, json, gzip, re, pathlib, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import econ_calendar as ec, preopen

FXD = ROOT / "tests" / "fixtures"


def get(url):
    q = re.search(r"date=(\d{4}-\d{2}-\d{2})", url).group(1)
    return json.loads(gzip.decompress((FXD / f"nasdaq_econ_q{q}.json.gz").read_bytes()))


ECON = lambda d: ec.fetch_econ(d, get)
q = lambda: contextlib.redirect_stdout(io.StringIO())
E = ec.expectations_for("PPI", ECON(dt.date(2026, 11, 13)))
assert "PPI — факт 0.3%, консенсус 0.4% (предишно 1.4%) · факт 6.5%, консенсус 6.6% (предишно 6.3%)" in E
def boom(d):
    raise ConnectionError("blocked")

print("── 1. РЕАЛНО: заглавието за PPI в карето от 13.11 — с очакванията ──")
x = {"title": "Wholesale prices rose 0.3% in October, putting annual rate at 6.5%, the highest in nearly four years", "source": "CNBC", "kind": "PPI",
     "published": "2026-11-13T14:02Z", "time_ny": "09:02", "time_berlin": "15:02"}
rows = [dict(x)]
preopen.attach_expectations(rows, ECON, dt.date(2026, 11, 13))
assert rows[0]["expectations"] == E and preopen.econ_line(rows[0]).endswith("— " + E)
rows2 = [dict(x)]
with q():
    preopen.attach_expectations(rows2, boom, dt.date(2026, 11, 13))
assert rows2[0]["expectations"] == "очаквания: не се провериха (Nasdaq: ConnectionError)"
rows3 = [dict(x)]
preopen.attach_expectations(rows3, None, dt.date(2026, 11, 13))
assert "expectations" not in rows3[0]
src_po = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert "calendar_fn=_calendar_fn())" in src_po
print(f"  ✓ „…6.5%, the highest in nearly four years“ · CNBC — {E[:60]}…")
print("\n✅ test_econ_expectations: всичко мина")
