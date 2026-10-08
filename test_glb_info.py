"""
GLB · честно име и информативни полета (09.10.2026, решения по проучването на Eric Wish).
  • Заглавието казва, че идеята (зелена линия = най-високият месечен close, ≥ 3 месеца без нов връх) е на Wish, а Classic/Momentum, филтърът band_hold и хистерезисът са НАШИ; „тесен base“ го няма — вместо него е числото
    „диапазон на 63 дни X% от линията“ (при Classic то беше 17–24%, т.е. не е тесен);
  • картата носи „обем на пробива ÷ средния“ (50 бара, без деня на пробива) и „× от 52-седмичното дъно“ — само информация, не филтър;
  • GLB_SEED_VERSION 2: състоянието от версия 1 (без новото поле) се гради наново от историята.

РЕАЛНО: tests/fixtures/glb_seed_2026-10-07.json (дневни барове с обем на FAST, ETN, ADI, NVT, CVX, QLYS, SNX, WCC, WSM до 07.10.2026) през glb_screener.breakout_volume_ratio / x_from_low52 / replay; РЕАЛНИТЕ карти на брифа от 05.10
(старият формат — без новите ключове) през dashboard-а. СИНТЕТИЧНО (маркирано): стойностите на новите полета върху картите в рендера, състоянието с белег версия 1, празната история.
Пускане: python test_glb_info.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import glb_screener as g, render

FX = json.loads((ROOT / "tests" / "fixtures" / "glb_seed_2026-10-07.json").read_text(encoding="utf-8"))["tickers"]
tmp = tempfile.TemporaryDirectory(prefix="mb_glbinfo_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()


def daily(sym):
    d = FX[sym]["daily"]
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))


print("── 1. обем на пробива ÷ средния: РЕАЛНИ дневни барове, независим цикъл ──")
n = config.GLB_VOLUME_AVG_BARS
assert n == 50
for sym in FX:
    h = daily(sym)
    for k in (len(h) - 1, len(h) - 20, 55):                                                   # последният бар и два по-ранни дни на пробив
        sub = h.iloc[:k + 1]
        prev = list(sub["Volume"].iloc[k - n:k])                                              # ръчно: точно n бара ПРЕДИ деня
        want = round(sub["Volume"].iloc[k] / (sum(prev) / n), 2)
        assert g.breakout_volume_ratio(sub) == want, (sym, k)
print(f"  ✓ {len(FX)} реални тикъра × 3 дни = {len(FX) * 3} сравнения: обемът на деня ÷ средния на предишните {n} бара (без самия ден) = ръчното смятане")
assert g.breakout_volume_ratio(daily("FAST").iloc[:n]) is None and g.breakout_volume_ratio(daily("FAST").iloc[:n + 1]) is not None
assert g.breakout_volume_ratio(daily("FAST").drop(columns="Volume")) is None and g.breakout_volume_ratio(daily("FAST").assign(Volume=0)) is None
print("  ✓ под 51 бара / липсващ обем / нулева средна → None (картата показва «н/д»)")

print()
print("── 2. × от 52-седмичното дъно ──")
assert g.x_from_low52(120.0, 80.0) == 1.5 and g.x_from_low52(100, 0) is None and g.x_from_low52(100, None) is None and g.x_from_low52("x", 5) is None
h = daily("WCC")
low = float(h["Low"].iloc[-252:].min())
assert g.x_from_low52(float(h["Close"].iloc[-1]), low) == round(float(h["Close"].iloc[-1]) / low, 2) and g.x_from_low52(float(h["Close"].iloc[-1]), low) > 1
print(f"  ✓ РЕАЛЕН WCC към 07.10: цена {float(h['Close'].iloc[-1]):.2f} ÷ най-ниско Low {low:.2f} = {g.x_from_low52(float(h['Close'].iloc[-1]), low)}×; невалидни входове → None")

print()
print("── 3. през целия път: събитията носят обема, редовете — × от дъното ──")
def hist_of(sym):
    f = FX[sym]
    m = pd.DataFrame({"Close": f["monthly"]["close"]}, index=pd.to_datetime(f["monthly"]["dates"]))
    m["Open"] = m["High"] = m["Low"] = m["Close"]; m["Volume"] = 0
    return pd.concat([m[["Open", "High", "Low", "Close", "Volume"]], daily(sym)]).sort_index()
g._verified_company_name = lambda s: {"name": s, "verified": True}
replays = {s: g.replay_observations(s, hist_of(s), config.GLB_SEED_SESSIONS, config.GLB_ENTRY_MARGIN_PCT) for s in FX}
events, rows, ch = g.replay_state(replays)
assert set(events) == set(FX) and len(rows) == 9
assert all("breakout_volume_ratio" in e for e in events.values()) and all(isinstance(e["breakout_volume_ratio"], float) and e["breakout_volume_ratio"] > 0 for e in events.values())
assert all(isinstance(r["x_from_52w_low"], float) and r["x_from_52w_low"] >= 1.0 for r in rows)
byt = {r["ticker"]: r for r in rows}
for sym, r in byt.items():
    hh = hist_of(sym)
    lowv = float(hh["Low"].loc[:"2026-10-07"].iloc[-252:].min())
    assert r["x_from_52w_low"] == round(r["price"] / lowv, 2) or abs(r["x_from_52w_low"] - r["price"] / lowv) < 0.011, (sym, r["x_from_52w_low"], r["price"] / lowv)
print("  ✓ 9 реални събития (FAST, ETN, ADI, NVT, CVX, QLYS, SNX, WCC, WSM): всяко носи breakout_volume_ratio (замразен в деня на входа), всеки ред — × от дъното, смятано всеки ден")
print("    обем на пробива: " + ", ".join(f"{s} {events[s]['breakout_volume_ratio']}×" for s in sorted(events)))

print()
print("── 4. версия на състоянието (СИНТЕТИЧНО: белег версия 1) ──")
state = pathlib.Path(tmp.name) / "glb_state.json"
state.write_text(json.dumps({"updated": "2026-10-08", "events": {"FAST": {"ticker": "FAST", "line": 1.0, "since": "2026-10-01", "glb_type": "classic", "prior_high": 1.0}}, "seed": {"version": 1, "sessions": 40, "from": "2026-08-12", "to": "2026-10-07"}}), encoding="utf-8")
assert g.load_seed_meta(state)["version"] == 1 < config.GLB_SEED_VERSION == 2
frames = {s: hist_of(s).assign(**{"Stock Splits": 0.0}) for s in FX}
big = pd.concat(frames, axis=1)
g.yf = type("Y", (), {"download": staticmethod(lambda batch, **kw: big[list(batch)])})
g.time = type("T", (), {"sleep": staticmethod(lambda s: None)})
with contextlib.redirect_stdout(io.StringIO()) as out:
    res = g.screen(universe=list(FX), batch_size=50, state_path=state, today="2026-10-09")
saved = json.loads(state.read_text(encoding="utf-8"))
assert "НАЧАЛНО състояние от историята" in out.getvalue() and saved["seed"]["version"] == 2 and all("breakout_volume_ratio" in e for e in saved["events"].values())
assert sorted(r["ticker"] for r in res) == sorted(FX) and all("x_from_52w_low" in r for r in res)
with contextlib.redirect_stdout(io.StringIO()) as out2:
    res2 = g.screen(universe=list(FX), batch_size=50, state_path=state, today="2026-10-09")
assert "НАЧАЛНО" not in out2.getvalue() and all("breakout_volume_ratio" in r for r in res2)
print("  ✓ състояние с белег версия 1 → еднократно ново изграждане (версия 2, събития с обема); втори run — обикновен хистерезис, полетата остават")

print()
print("── 5. етикетите и страницата ──")
for k, v in g.RISK_NOTES.items():
    claim = v.lower().replace('не е доказателство за "тесен" base', "")                           # единственото място, където думата е, е изричното отрицание
    assert "тесен" not in claim and "tight" not in claim and "най-близък до класически Stage 2" not in v, k
assert "наш филтър" in g.RISK_NOTES["classic"].lower() and "не на Wish" in g.RISK_NOTES["classic"] and "наш филтър" in g.RISK_NOTES["momentum"].lower()
import re as _re
_mixed = _re.compile(r"\b(?=\w*[A-Za-z])(?=\w*[А-Яа-я])\w+\b")                                                  # дума от кирилица И латиница (като «момentum», «orязана»)
tpl_head = (ROOT / "templates" / "dashboard.html.j2").read_text(encoding="utf-8")
tpl_head = tpl_head[tpl_head.index("GLB Watchlist · Green Line Breakout"):][:3200]
for label, txt in [*g.RISK_NOTES.items(), ("заглавие на секцията", tpl_head)]:
    assert not _mixed.findall(txt), (label, _mixed.findall(txt))
print("  ✓ в бележките на картите и в заглавието на секцията няма смесени кирилица/латиница думи")
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
assert B05["glb_candidates"] and "breakout_volume_ratio" not in B05["glb_candidates"][0]                   # РЕАЛНИТЕ карти от 05.10 са в стария формат
with contextlib.redirect_stdout(io.StringIO()):
    page_old = render.render_dashboard(copy.deepcopy(B05))
sec = page_old[page_old.index("GLB Watchlist · Green Line Breakout"):]
sec = sec[:sec.index("</section>")]
head = sec[:sec.index('class="glb-card')] if 'class="glb-card' in sec else sec[:1800]
assert "Идеята е на Eric Wish" in head and "Наши са:" in head and "Classic / Momentum" in head and "тесен" not in head.lower() and "tightness" not in head
assert "обем на пробива н/д · дъно н/д" in sec and "диапазон на 63 дни" in sec and "±" not in sec.split("band_hold")[1][:80]
print("  ✓ РЕАЛНИТЕ карти от 05.10 (стар формат, без новите ключове): заглавието «Идеята е на Eric Wish … Наши са: …» без «тесен»/«tightness»; редът с новите полета — «н/д» (без изключение); диапазонът е «диапазон на 63 дни X% от линията», не «±»")
assert "Тесен, добре удържан base" in sec                                                                  # архивният бриф пази СЪХРАНЕНАТА бележка на деня си — не се пренаписва
print("  ✓ архивният бриф от 05.10 пази съхранената бележка на своя ден («Тесен, добре удържан base …») — старите брифове не се пренаписват")
cur = copy.deepcopy(B05)
cur["glb_candidates"] = [{**r, "company": r.get("company") or r["ticker"]} for r in rows]                  # карти от СЕГАШНИЯ код върху реалните барове от фиксчъра (стъпка 3)
with contextlib.redirect_stdout(io.StringIO()):
    page_cur = render.render_dashboard(cur)
sec2 = page_cur[page_cur.index("GLB Watchlist · Green Line Breakout"):]
sec2 = sec2[:sec2.index("</section>")]
claim2 = re.sub(r"не е доказателство за (&#34;|\")тесен(&#34;|\") base", "", sec2.lower())                      # единственото място с думата е изричното отрицание в бележката на Classic
assert "тесен" not in claim2 and "tightness" not in claim2 and "Наш филтър (не на Wish)" in sec2 and sec2.count("не е доказателство за") == sum(r["glb_type"] == "classic" for r in rows)
assert sec2.count("(наш филтър, не на Wish)") == sum(r["glb_type"] == "momentum" for r in rows)
assert "обем на пробива н/д" not in sec2 and sec2.count("× от 52-седм. дъно") == len(rows)
print(f"  ✓ {len(rows)} карти, построени от сегашния код върху реалните барове: бележката «Наш филтър (не на Wish) …», без «тесен»; всяка носи «обем на пробива …× средния · …× от 52-седм. дъно»")
b = copy.deepcopy(B05)
for c in b["glb_candidates"]:
    c["breakout_volume_ratio"], c["x_from_52w_low"] = 1.84, 2.31                                            # СИНТЕТИЧНО
with contextlib.redirect_stdout(io.StringIO()):
    page_new = render.render_dashboard(b)
assert "обем на пробива 1.8× средния · 2.3× от 52-седм. дъно" in page_new
print("  ✓ СИНТЕТИЧНО (1.84 / 2.31): «обем на пробива 1.8× средния · 2.3× от 52-седм. дъно»")
print("\n✅ test_glb_info: всичко мина")
