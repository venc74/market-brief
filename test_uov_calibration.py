"""
UOV✓ · калибриране (08.10.2026). В брифа на 08.10 съотношенията обем/OI на нашите тикъри бяха 0.09–0.29 при абсолютен праг 2.0 — с прозорец от 21 дни маркерът е недостижим. Сега прагът е относителен:
перцентил (P90) спрямо РЕФЕРЕНТНА КОШНИЦА от ликвидни тикъри за същата сесия, а когато тикърът има поне 20 собствени наблюдения — спрямо СОБСТВЕНАТА история; абсолютният праг 2.0 остава като допълнителен път.
Следобедната снимка на OI носи и кошницата (snap["reference"]).

РЕАЛНО: tests/fixtures/uov_basket_live_2026-10-08.json — ЖИВИ опционни вериги от Yahoo за топ 60 по ликвидност от S&P500+NDX (59 с вериги), 08.10.2026 ~17:30 CEST (11:30 ET, сесията тече — обемът е
ЧАСТИЧЕН ден; OI е в началото на сесията), суми по падеж [call_vol, call_oi, put_vol, put_oi] за падежите в (08.10, 05.11]. Из тях тестът смята реалното разпределение на съотношенията.
СИНТЕТИЧНО (маркирано): снимката е сглобена от реалния OI на fixture-а (сесия 07.10, "заснета" 16:01 UTC), нашите тикъри (подмножество на кошницата + AAA), собствената история, часовникът, бюджетът.
Реалните съотношения на нашите тикъри от брифа на 08.10 (0.09–0.29) са пълен ден — сравнението с частичния ден на кошницата е само ориентир.
Пускане: python test_uov_calibration.py
"""
import sys, json, pathlib, tempfile, types, datetime as dt, contextlib, io
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import config
from src import unusual_options as uo, oi_snapshot, data_warnings

D = dt.date.fromisoformat
FX = json.loads((ROOT / "tests" / "fixtures" / "uov_basket_live_2026-10-08.json").read_text(encoding="utf-8"))
CH, BASKET = FX["chains"], FX["basket"]
TODAY, SESSION = D("2026-10-08"), "2026-10-07"                               # СИНТЕТИЧНО: денят на брифа и сесията, на която "принадлежи" снимката (OI е реален, от 08.10)
tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_uovcal_"))
config.UNUSUAL_OPTIONS_HISTORY_FILE = tmp / "uov_ratio_history.json"


class Chain:
    def __init__(self, c, p):
        self.calls, self.puts = c, p


CALLS = {"n": 0}


class FakeTicker:
    def __init__(self, per):                                                 # {падеж: [cv, co, pv, po]}
        self.per, self.options = per, tuple(sorted(per))

    def option_chain(self, exp):
        CALLS["n"] += 1
        cv, co, pv, po = self.per[exp]
        mk = lambda v, o: pd.DataFrame({"volume": [v], "openInterest": [o]})
        return Chain(mk(cv, co), mk(pv, po))


def real_ratio(sym):
    """Независимо от модула: сума(обем)/сума(OI) по падежите в (08.10, 29.10] с OI > 0."""
    rows = [v for e, v in CH[sym].items() if TODAY < D(e) <= TODAY + dt.timedelta(days=21) and v[1] + v[3] > 0]
    oi = sum(v[1] + v[3] for v in rows)
    return sum(v[0] + v[2] for v in rows) / oi if oi >= 50 else None


EXTRA = {"AAA": {"2026-10-09": [3000, 100, 1000, 100], "2026-10-16": [500, 50, 500, 50]}}          # СИНТЕТИЧЕН тикър извън кошницата: 5000 / 300 = 16.7×
SNAP = {"horizon_days": 28, "fetched_at_utc": "2026-10-07 16:01", "reference": list(BASKET),
        "tickers": {s: {e: v[1] + v[3] for e, v in per.items()} for s, per in {**CH, **EXTRA}.items()}}
uo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker({**CH, **EXTRA}.get(sym, {})))                      # тикър без верига (EA — делистнат в Yahoo) → празни падежи
uo._snapshot_for_yesterday = lambda today: (SNAP, SESSION, "")

print("── 1. РЕАЛНОТО разпределение на съотношенията в кошницата (частичен ден, 08.10) ──")
ratios = {s: real_ratio(s) for s in CH if real_ratio(s) is not None}
v = sorted(ratios.values())
assert len(v) == 59
for q in (10, 50, 90, 95):
    assert abs(uo.percentile(v, q) - float(np.percentile(v, q))) < 1e-12                                          # перцентилът = numpy (линейна интерполация)
P50, P90, P95 = (float(np.percentile(v, q)) for q in (50, 90, 95))
top = sorted(ratios.items(), key=lambda x: -x[1])[:3]
print(f"  ✓ 59 тикъра: P50 = {P50:.3f}×, P90 = {P90:.3f}×, P95 = {P95:.3f}×, най-високи {', '.join(f'{s} {r:.2f}×' for s, r in top)}; абсолютният праг 2.0× е {2.0 / P90:.1f} пъти над P90")
assert 0.05 < P50 < 0.15 and 0.15 < P90 < 0.40 and max(v) < 2.0
print("    (нашите тикъри в РЕАЛНИЯ бриф на 08.10: 0.09–0.29 → между P50 и P90 на това разпределение; праг 2.0× не е сработвал за нито един от 8 тикъра)")

print()
print("── 2. reference_basket през реалния analyze_ticker ──")
CALLS["n"] = 0
b = uo.reference_basket(SNAP, SESSION, TODAY)
n1 = CALLS["n"]
assert b["reference"] == 60 and b["valid"] == 59 and not b["stopped"] and set(b["missing"]) == set(BASKET) - set(CH), (b["valid"], b["missing"])
assert all(abs(b["ratios"][s] - ratios[s]) < 1e-3 for s in b["ratios"]), "съотношенията през модула = независимото смятане"
assert abs(b["p"] - P90) < 1e-3 and abs(b["median"] - P50) < 1e-3
assert len(b["missing"]) == 1 and "няма опционна верига" in next(iter(b["missing"].values()))
print(f"  ✓ {b['valid']} от {b['reference']} валидни; P90 = {b['p']:.4f}, медиана = {b['median']:.4f} (= независимото смятане); тикърът без верига е в missing с причина")
b2 = uo.reference_basket(SNAP, SESSION, TODAY)
assert b2 is b and CALLS["n"] == n1
print(f"  ✓ втори извикване за същата сесия: от паметта ({n1} заявки за вериги общо, нула нови) — кандидати и позиции викат candidate_markers поотделно")
uo._BASKET_MEMO.clear(); uo._ANALYSIS_MEMO.clear()
tick = iter(range(0, 10000, 100))
bs = uo.reference_basket(SNAP, SESSION, TODAY, budget_sec=250, clock=lambda: next(tick))                      # СИНТЕТИЧЕН часовник: +100 с на всяко четене
assert bs["stopped"] and bs["valid"] < config.UNUSUAL_OPTIONS_REFERENCE_MIN_VALID and bs["p"] is None and "спряно по бюджета" in bs["reason"]
print(f"  ✓ СИНТЕТИЧНО: бюджет от 250 с при часовник +100 с/четене → спира след {bs['valid']} тикъра, прагът липсва (под {config.UNUSUAL_OPTIONS_REFERENCE_MIN_VALID} валидни), причина: «{bs['reason']}»")
uo._BASKET_MEMO.clear(); uo._ANALYSIS_MEMO.clear()
nb = uo.reference_basket({**SNAP, "reference": []}, SESSION, TODAY)
assert nb["p"] is None and nb["reason"] == "снимката няма референтна кошница"
nb2 = uo.reference_basket(None, SESSION, TODAY, "следобедната OI снимка липсва")
assert nb2["p"] is None and nb2["reason"] == "следобедната OI снимка липсва"
print("  ✓ СИНТЕТИЧНО: снимка без кошница / без снимка → без праг, с причина")
uo._BASKET_MEMO.clear(); uo._ANALYSIS_MEMO.clear()

print()
print("── 3. решението за маркер (чиста функция) ──")
basket = uo.reference_basket(SNAP, SESSION, TODAY)
hi, lo = P90 * 1.1, P90 * 0.9
d_hi, d_lo = uo.marker_decision("X", hi, basket, []), uo.marker_decision("X", lo, basket, [])
assert d_hi["marked"] and d_hi["mode"] == "day" and d_hi["percentile"] >= 90 and abs(d_hi["threshold"] - P90) < 1e-3
assert not d_lo["marked"] and d_lo["mode"] == "day" and d_lo["percentile"] < 90
print(f"  ✓ за деня: {hi:.3f}× (над P90 {P90:.3f}×) → маркер, перцентил {d_hi['percentile']}; {lo:.3f}× → без маркер, перцентил {d_lo['percentile']}")
none_basket = {"p": None, "ratios": {}, "reason": "снимката няма референтна кошница"}
d_abs = uo.marker_decision("X", 2.5, none_basket, [])
d_no = uo.marker_decision("X", 0.5, none_basket, [])
assert d_abs["marked"] and d_abs["mode"] == "absolute" and not d_no["marked"] and "няма с какво да се сравни" in d_no["why"]
print("  ✓ СИНТЕТИЧНО: без кошница и без история: ≥ 2.0× пак маркира (абсолютният път), по-малко — без маркер и с причина «няма с какво да се сравни»")
prior = [0.10 + 0.01 * i for i in range(25)]                                                                       # СИНТЕТИЧНА история от 25 наблюдения: 0.10 … 0.34
h1, h2 = uo.marker_decision("X", 0.50, basket, prior), uo.marker_decision("X", 0.20, basket, prior)
assert h1["mode"] == "history" and h1["marked"] and h1["percentile"] == 100.0 and h1["history_days"] == 25
assert h2["mode"] == "history" and not h2["marked"] and 30 < h2["percentile"] < 50
assert not uo.marker_decision("X", 0.20, basket, prior[:19])["mode"] == "history"                                   # 19 наблюдения < 20 → още за деня
print("  ✓ СИНТЕТИЧНО: с ≥ 20 собствени наблюдения решава историята (0.50× → перцентил 100 → маркер; 0.20× → перцентил ~40 → без маркер, макар да е над P90 на кошницата); с 19 — още за деня")
assert uo.percent_rank([1, 2, 3, 4], 2.5) == 50.0 and uo.percent_rank([1, 1, 1], 1) == 50.0 and uo.percent_rank([], 1) is None and uo.percentile([], 90) is None
print("  ✓ СИНТЕТИЧНО: percent_rank (равните наполовина) и percentile на празен списък")

print()
print("── 4. candidate_markers от край до край: РЕАЛНИ вериги на тикъри от кошницата + AAA (СИНТЕТИЧЕН) ──")
ours = ["PLTR", "TSLA", "KEY", "AAA", "NOPE"]                                                                       # NOPE: извън снимката
uo._BASKET_MEMO.clear(); uo._ANALYSIS_MEMO.clear()
uo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker({**CH, **EXTRA}[sym]) if sym in {**CH, **EXTRA} else FakeTicker({"2026-10-09": [1, 1, 1, 1]}))
with contextlib.redirect_stdout(io.StringIO()) as out:
    mk, diag = uo.candidate_markers(ours, TODAY)
assert sorted(mk) == ["AAA", "PLTR", "TSLA"], sorted(mk)
assert mk["PLTR"]["mode"] == "day" and mk["TSLA"]["mode"] == "day" and mk["AAA"]["mode"] == "day"
assert "KEY" not in mk and diag["decisions"]["KEY"]["marked"] is False and diag["decisions"]["KEY"]["percentile"] < 10
note = mk["PLTR"]["note"]
assert f"≈ {ratios['PLTR']:.2f}× OI — над 90-ия перцентил на 59 ликвидни тикъра за деня (праг {P90:.2f}×)" in note and "сесията 07.10" in note, note
assert diag["basket"]["valid"] == 59 and abs(diag["basket"]["p"] - P90) < 1e-3 and diag["percentile"] == 90 and diag["history_min_days"] == 20
assert diag["with_ratio"] == 4 and diag["marked"] == 3 and "NOPE" in diag["missing"] and not diag["no_basis"]
print(f"  ✓ маркери: PLTR {ratios['PLTR']:.2f}×, TSLA {ratios['TSLA']:.2f}× (реално най-високите в кошницата) и AAA 16.7× (синтетичен); KEY ({ratios['KEY']:.3f}×, най-ниското) — не")
print("    текст при hover/клик (PLTR):", note)
hist = uo.load_ratio_history()
assert set(hist) == set(b["ratios"]) | {"AAA"} and all(list(o) == [SESSION] for o in hist.values()), (len(hist))
assert abs(hist["PLTR"][SESSION] - ratios["PLTR"]) < 1e-3
print(f"  ✓ историята е допълнена за сесия {SESSION}: {len(hist)} тикъра (кошницата + нашите), по едно наблюдение")
uo._BASKET_MEMO.clear(); uo._ANALYSIS_MEMO.clear()
with contextlib.redirect_stdout(io.StringIO()):
    uo.candidate_markers(ours, TODAY)
assert uo.load_ratio_history() == hist
print("  ✓ повторно пускане за същата сесия е идемпотентно (същата история)")

print()
print("── 5. когато историята вече решава (СИНТЕТИЧНА история от 25 предишни сесии за PLTR и KEY) ──")
syn = {t: dict(o) for t, o in hist.items()}
syn["PLTR"] = {f"2026-09-{d:02d}": 0.8 + 0.02 * k for k, d in enumerate(range(1, 26))}                           # PLTR обикновено е 0.8–1.3× → днешните 0.83× не са необичайни за него
syn["PLTR"][SESSION] = hist["PLTR"][SESSION]
syn["KEY"] = {f"2026-09-{d:02d}": 0.005 + 0.0003 * k for k, d in enumerate(range(1, 26))}                         # KEY обикновено е 0.005–0.012× → днешните 0.014× са над цялата му история
syn["KEY"][SESSION] = hist["KEY"][SESSION]
uo.save_ratio_history(syn)
uo._BASKET_MEMO.clear(); uo._ANALYSIS_MEMO.clear()
with contextlib.redirect_stdout(io.StringIO()):
    mk2, diag2 = uo.candidate_markers(["PLTR", "KEY", "TSLA"], TODAY)
assert "PLTR" not in mk2 and diag2["decisions"]["PLTR"]["mode"] == "history" and diag2["decisions"]["PLTR"]["percentile"] < 10
assert "KEY" in mk2 and mk2["KEY"]["mode"] == "history" and mk2["KEY"]["percentile"] == 100.0
assert "TSLA" in mk2 and mk2["TSLA"]["mode"] == "day"                                                              # без история → още за деня
assert "собствената му история" in mk2["KEY"]["note"] and "25 дни" in mk2["KEY"]["note"]
print(f"  ✓ PLTR ({ratios['PLTR']:.2f}×, над P90 на кошницата) вече НЕ е маркиран — за него е обичайно (перцентил {diag2['decisions']['PLTR']['percentile']}); KEY ({ratios['KEY']:.3f}×, най-ниското в кошницата) Е маркиран — над цялата му собствена история; TSLA без история — още за деня")
print("    текст (KEY):", mk2["KEY"]["note"])
assert uo.load_ratio_history()["KEY"][SESSION] == hist["KEY"][SESSION] and len(uo.load_ratio_history()["KEY"]) == 26
rec = uo.record_ratios({"X": {f"2026-01-{d:02d}": 1.0 for d in range(1, 11)}}, "2026-02-01", {"X": 2.0, "Y": 3.0}, keep=5)
assert list(rec["X"]) == ["2026-01-07", "2026-01-08", "2026-01-09", "2026-01-10", "2026-02-01"] and rec["Y"] == {"2026-02-01": 3.0}
bad = tmp / "bad.json"; bad.write_text("{не е json", encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    assert uo.load_ratio_history(bad) == {} and uo.load_ratio_history(tmp / "няма.json") == {}
print("  ✓ СИНТЕТИЧНО: историята пази най-много `keep` най-нови дати на тикър; повреден/липсващ файл → празна история без изключение")

print()
print("── 6. без кошница днес → банер (маркер само при абсолютния праг) ──")
w = data_warnings.collect(None, None, uov_diag={"requested": 3, "with_ratio": 3, "missing": {}, "min_ratio": 2.0, "basket": {"p": None, "reason": "снимката няма референтна кошница"}, "decisions": {"A": {"mode": "absolute"}}})
assert len(w) == 1 and "няма референтна кошница за деня (снимката няма референтна кошница)" in w[0]["message"] and "НЕ значи нормален обем" in w[0]["message"]
ok1 = data_warnings.collect(None, None, uov_diag={"requested": 3, "with_ratio": 3, "missing": {}, "basket": {"p": 0.26}, "decisions": {}})
ok2 = data_warnings.collect(None, None, uov_diag={"requested": 3, "with_ratio": 3, "missing": {}, "basket": {"p": None}, "decisions": {"A": {"mode": "history"}}})
old = data_warnings.collect(None, None, uov_diag={"requested": 3, "with_ratio": 3, "missing": {}})                 # формат преди 08.10 — без ключа basket
assert ok1 == [] and ok2 == [] and old == []
print("  ✓ СИНТЕТИЧНО: банер само когато няма нито праг от кошницата, нито решение по история; с кошница, с история и в стария формат на diag — без банер")

print()
print("── 7. следобедната снимка носи кошницата, а straddle-ите са само за нашите тикъри ──")
class FixedDT(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return dt.datetime(2026, 10, 7, 15, 0, tzinfo=dt.timezone.utc).astimezone(tz) if tz else dt.datetime(2026, 10, 7, 15, 0)
orig_dt = oi_snapshot.dt
oi_snapshot.dt = types.SimpleNamespace(date=dt.date, timedelta=dt.timedelta, timezone=dt.timezone, datetime=FixedDT)
seen = {}
uo.yf = types.SimpleNamespace(Ticker=lambda sym: FakeTicker({**CH, **EXTRA}.get(sym, {})))                      # делистнатият тикър от кошницата няма падежи → не влиза в снимката
uo.last_session_date = lambda: D("2026-10-07")
uo.load_oi_snapshots = lambda: {}
uo._sp500_ndx_universe = lambda: list(BASKET)
uo._top_by_volume = lambda universe, n: list(BASKET)[:n]
oi_snapshot.snapshot_tickers = lambda: ["PLTR", "AAA"]
oi_snapshot._window_oi = lambda tk, session: {e: v[1] + v[3] for e, v in tk.per.items()}
oi_snapshot.earnings_move = types.SimpleNamespace(snapshot_straddles=lambda tickers, session, yf: seen.setdefault("straddle_tickers", list(tickers)) and {})
with contextlib.redirect_stdout(io.StringIO()):
    snap = oi_snapshot.take_snapshot()
oi_snapshot.dt = orig_dt
assert snap["session_date"] == SESSION and snap["horizon_days"] == 28
assert snap["reference"] == [t for t in BASKET if t in snap["tickers"]] and len(snap["reference"]) == 59 and "AAA" in snap["tickers"] and "AAA" not in snap["reference"]
assert seen["straddle_tickers"] == ["PLTR", "AAA"], seen
print("  ✓ снимката: нашите тикъри (PLTR, AAA) + кошницата от 60 (59 с вериги) → snap['reference'] = 59 тикъра; straddle-ите за отчети са поискани САМО за PLTR и AAA")
print("\n✅ test_uov_calibration: всичко мина")
