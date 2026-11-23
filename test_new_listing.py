"""
17.11.2026 (пакет 1, т. 10): нова на борсата (HONA, отделена от Honeywell) — редът на наблюдаваните казваше „−45.1% от 52-седм. връх“: върхът беше от първите дни на
търговия (Yahoo: 109 бара от 15.06.2026, най-високият High $297.50). Сега: под config.WATCH_52W_MIN_BARS (240) собствени бара — „на борсата от ДД.ММ.ГГГГ — без 52-седм.
показатели“; празните дни преди листването падат (само собствената история).

РЕАЛНО: tests/fixtures/hona_daily_2026-11-17.json — дневните бари на HONA от Yahoo (1y), изтеглени 17.11.2026. СИНТЕТИЧНО (означено): т. 2 — 260 бара на тикър с пълна история.
Пускане: python test_new_listing.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import watch_monitor as wm

B = json.loads((ROOT / "tests" / "fixtures" / "hona_daily_2026-11-17.json").read_text(encoding="utf-8"))["bars"]
idx = pd.to_datetime([b["date"] for b in B])
H, L, C = (pd.Series([b[k] for b in B], index=idx) for k in ("h", "l", "c"))

print("── 1. РЕАЛНО: HONA — 109 бара ──")
full = pd.date_range("2025-11-17", "2026-11-17", freq="B")                                   # както при общото теглене с SPY: дните преди листването — празни
r = wm.range_facts(H.reindex(full), L.reindex(full), C.reindex(full))
assert r["listed_since"] == "2026-06-15" and r["history_bars"] == 109 and "off_high_pct" not in r and "high_52w" not in r and "adr_pct" in r
print(f"  ✓ на борсата от 15.06.2026, без 52-седм. показатели (до 17.11 — {(C.iloc[-1] / H.max() - 1) * 100:.1f}% „от 52-седм. връх“)")

print("── 2. СИНТЕТИЧНО: пълна история — както досега ──")
d = pd.date_range("2025-11-01", periods=260, freq="B")
s = pd.Series(range(100, 360), index=d, dtype=float)
r2 = wm.range_facts(s + 1, s - 1, s)
assert "listed_since" not in r2 and r2["off_high_pct"] == round((359 / 360 - 1) * 100, 1)
print("  ✓ 260 бара — разстоянието до 52-седм. връх, без етикет")

tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "на борсата от {{ p.listed_since[8:10] }}.{{ p.listed_since[5:7] }}.{{ p.listed_since[:4] }} — без 52-седм. показатели" in tpl and config.WATCH_52W_MIN_BARS == 240
print("\n✅ test_new_listing: всичко мина")
