"""
17.11.2026 (пакет 2, т. 2 — А4): „Чака пробив“ → аларма с обем. Картата: „Аларма над $X — вход само с обем“ + нужният обем до 10:30 / 12:00 / 14:00 Ню Йорк за ден с 1.5×
средния — по собствения профил на акцията (5-мин. бари, ~20 сесии), иначе по общия (медианата на 20 ликвидни акции × 21 сесии до 17.11: 21.2% / 40.0% / 60.0%) с етикет.
Книгата записва както досега (при докосване); всеки запис — „обемът потвърди“ / „не потвърди“; обобщението — по двата етикета.

РЕАЛНО: tests/fixtures/rga_5m_volume_2026-11-17.json — 5-мин. обем на RGA (Yahoo, 1 месец); volume_profiles_2026-11-17.json — дяловете на 20-те акции (общият профил);
картата на RGA от 17.11 (buy-stop $272.44, среден обем 429 676 — data/2026-11-17.json, цитирано). СИНТЕТИЧНО (означено): т. 3 — карта без среден обем; последната сесия
в данните (17.11) е непълна и се пропуска (< 70 бара).
Пускане: python test_volume_alarm.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, statistics, pathlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import volume_alarm as va

FXD = ROOT / "tests" / "fixtures"
R = json.loads((FXD / "rga_5m_volume_2026-11-17.json").read_text(encoding="utf-8"))
V = pd.Series(R["volume"], index=pd.to_datetime(R["utc"], utc=True))
P = json.loads((FXD / "volume_profiles_2026-11-17.json").read_text(encoding="utf-8"))["days"]
CARD = {"ticker": "RGA", "avg_volume_50d": 429676, "setup": {"kind": "below_pivot", "buy_stop": 272.44, "triggered": False}}

print("── 1. РЕАЛНО: общият профил = медианата на 20-те акции ──")
med = {t: round(statistics.median(statistics.mean(d[t] for d in days) for days in P.values()), 3) for t in config.VOLUME_ALARM_TIMES}
assert med == config.VOLUME_PROFILE_GENERIC == {"10:30": 0.212, "12:00": 0.4, "14:00": 0.6}, med
print(f"  ✓ {med} ({len(P)} акции)")

print("── 2. РЕАЛНО: собственият профил на RGA ──")
p = va.profile(V)
assert p["days"] == 20 and 0.08 < p["10:30"] < 0.15 and p["10:30"] < p["12:00"] < p["14:00"] < 1, p
a = va.alarm(CARD, p)
assert a["source"] == "own" and a["day"] == round(1.5 * 429676) and a["text"].startswith("Аларма над $272.44 — вход само с обем: до 10:30 Ню Йорк ≥ ")
assert f"· собствен профил ({p['days']} сесии)" in a["text"]
print(f"  ✓ {a['text']}")

print("── 3. без профил — общият с етикет; без среден обем — нищо ──")
g = va.alarm(CARD, None)
assert g["source"] == "generic" and "общ профил — собственият липсва" in g["text"] and g["need"][0]["shares"] == round(1.5 * 429676 * 0.212)
assert va.alarm({**CARD, "avg_volume_50d": None}, p) is None                                          # СИНТЕТИЧНО
wl = [dict(CARD), {**CARD, "ticker": "X", "setup": {"kind": "below_pivot", "buy_stop": 10, "triggered": True}}]
assert va.annotate(wl, {"RGA": p}) == 1 and "volume_alarm" in wl[0] and "volume_alarm" not in wl[1]
print("  ✓ общият профил — с етикета; задействан запис — без аларма")

print("── 4. картата, имейлът, книгата ──")
tpl = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
assert "<b>Аларма:</b> {{ st.volume_alarm.text }}" in tpl and "{% macro vol_label(r, mult) %}" in tpl and "обемът не потвърди" in tpl
assert 'st["volume_alarm"]["text"]' in (ROOT / "src" / "render.py").read_text(encoding="utf-8")
assert 'steps.step("volume_alarm", _volume_alarm' in (ROOT / "src" / "main.py").read_text(encoding="utf-8")
print("  ✓ редът „Аларма:“ на картата и в имейла; книгите — етикетът на записа и статистиката по него")
print("\n✅ test_volume_alarm: всичко мина")
