"""
Watchlist · "Излязоха от вчера" (09.10.2026): тикърите от Watchlist на предишния бриф, които днес ги няма, с причината от кода (src/watchlist_exits.py). Само информация — Action/Watchlist не се променят.

РЕАЛНО: tests/fixtures/watchlist_exits_2026-10-09.json — Watchlist на брифа от 08.10 (с числата на сетъпите), тикърите на 09.10 (Watchlist: EXPD, ANET, ZBRA, AMG, PSX, FTNT, NTAP; Action: няма) и РЕАЛНИТЕ причини, върнати от
screener.explain_exits на 09.10 за AMD, DINO, KEYS, VLO (записани, не изчислявани в теста). Излезли между двата бриф-а: AMD, VLO, DINO, KEYS (всичките "твърде разтегнато" вчера). СИНТЕТИЧНО (маркирано): кандидатът извън
10-те карти, провалът на explain, нечетимите/липсващите snapshot-и и датите за понеделник.
Пускане: python test_watchlist_exits.py
"""
import sys, json, pathlib, tempfile, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import watchlist_exits as wx, render

FX = json.loads((ROOT / "tests" / "fixtures" / "watchlist_exits_2026-10-09.json").read_text(encoding="utf-8"))
tmp = tempfile.TemporaryDirectory(prefix="mb_wlx_")
D = pathlib.Path(tmp.name) / "data"; D.mkdir()
config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"; config.DOCS_DIR.mkdir(); config.DATA_DIR = D
(D / "2026-10-08.json").write_text(json.dumps({"date": "2026-10-08", "watchlist": FX["prior_watchlist"]}, ensure_ascii=False), encoding="utf-8")
(D / "2026-10-07.json").write_text(json.dumps({"date": "2026-10-07", "watchlist": [{"ticker": "OLD", "setup": {}}]}), encoding="utf-8")
(D / "2026-10-09.json").write_text(json.dumps({"date": "2026-10-09", "watchlist": [{"ticker": "SAMEDAY", "setup": {}}]}), encoding="utf-8")   # денят на брифа — не е "предишен"
(D / "glb_state.json").write_text("{}", encoding="utf-8")                                                                                       # не е snapshot (името не е дата)
TODAY_WL = [{"ticker": t} for t in FX["today_watchlist"]]

print("── 1. РЕАЛНИТЕ данни 08.10 → 09.10 ──")
d, prior = wx.prior_watchlist("2026-10-09", D)
assert d == "2026-10-08" and [c["ticker"] for c in prior] == ["ZBRA", "ANET", "AMD", "VLO", "DINO", "KEYS", "FTNT", "NTAP"]
calls = []
def explain(tickers):
    calls.append(list(tickers))
    return {t: FX["explain"][t] for t in tickers}
info = wx.run("2026-10-09", [], TODAY_WL, [{"ticker": c["ticker"]} for c in TODAY_WL], explain=explain, data_dir=D)
assert info["from"] == "2026-10-08" and [r["ticker"] for r in info["rows"]] == ["AMD", "VLO", "DINO", "KEYS"] and calls == [["AMD", "DINO", "KEYS", "VLO"]]
byt = {r["ticker"]: r for r in info["rows"]}
struct = {c["ticker"]: c["setup"]["struct_risk_pct"] for c in FX["prior_watchlist"]}
for t in ("AMD", "VLO", "DINO", "KEYS"):
    assert byt[t]["reason"] == FX["explain"][t] and byt[t]["kind"] == "screener"
    assert byt[t]["yesterday"] == f"структурен стоп {struct[t]:.1f}% > 10%", (t, byt[t]["yesterday"])
print("  ✓ излезли: " + "; ".join(f"{r['ticker']}: {r['reason']} (вчера: {r['yesterday']})" for r in info["rows"]))
assert "OLD" not in str(info) and "SAMEDAY" not in str(info)
print("  ✓ предишен бриф = най-новият със строго по-ранна дата (07.10 и брифът от същия ден не се ползват); glb_state.json не е snapshot")

print()
print("── 2. граници (СИНТЕТИЧНИ) ──")
action = [{"ticker": "AMD"}]                                                                      # AMD е станал Action → не е "излязъл"
cands = [{"ticker": "VLO", "setup": {"kind": "too_wide", "struct_risk_pct": 14.8}}, {"ticker": "DINO", "setup": {"kind": "below_pivot"}}, {"ticker": "KEYS", "setup": {}}]
rows = wx.compute(prior, action, TODAY_WL, cands, explain=lambda t: {})
by = {r["ticker"]: r for r in rows}
assert "AMD" not in by and sorted(by) == ["DINO", "KEYS", "VLO"]
assert by["VLO"]["kind"] == "limit" and by["VLO"]["reason"] == "в скрийнъра, но извън 10-те карти (структурен стоп 14.8% > 10%)"
assert by["DINO"]["reason"] == "в скрийнъра, но извън 10-те карти (под pivot — чака buy-stop)" and by["KEYS"]["reason"] == "в скрийнъра, но извън 10-те карти"
with contextlib.redirect_stdout(io.StringIO()):
    rows = wx.compute(prior, [], TODAY_WL, [], explain=lambda t: (_ for _ in ()).throw(RuntimeError("Yahoo")))
assert {r["reason"] for r in rows} == {"не е в днешния технически списък"}
rows = wx.compute(prior, [], TODAY_WL, [], explain=None)
assert len(rows) == 4
assert wx.run("2026-10-09", [], TODAY_WL, [], explain=explain, data_dir=D / "няма") == {}
(D / "2026-10-08.json").write_text("{не е json", encoding="utf-8")
with contextlib.redirect_stdout(io.StringIO()):
    d2, p2 = wx.prior_watchlist("2026-10-09", D)
assert d2 == "2026-10-07" and [c["ticker"] for c in p2] == ["OLD"]                                  # нечетим snapshot се прескача към следващия по-стар
(D / "2026-10-08.json").write_text(json.dumps({"date": "2026-10-08", "watchlist": FX["prior_watchlist"]}, ensure_ascii=False), encoding="utf-8")
assert wx.setup_text({"kind": "extended"}) == "над +5% от pivot" and wx.setup_text({"kind": "no_volume"}) == "над pivot без обем ≥ 1.5×" and wx.setup_text({"kind": "confirmed"}) == "потвърден пробив" and wx.setup_text(None) is None and wx.setup_text({"kind": "too_wide"}) is None
print("  ✓ Action не е изход; кандидат извън 10-те карти → причина «извън 10-те карти» + сетъпът; провал на explain / липса на explain → общ текст; няма предишен бриф → {}; нечетим snapshot се прескача")

print()
print("── 3. страницата и имейлът ──")
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B05); b["date"] = "2026-10-09"; b["watchlist_exits"] = info
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(copy.deepcopy(b)); mail = render.render_email(copy.deepcopy(b))
import re
def txt(h, key):
    i = h.index(key); return " ".join(__import__("html").unescape(re.sub(r"<[^>]+>", "", h[i:i + 1400])).split())
for name, h in (("страница", page), ("имейл", mail)):
    t = txt(h, "Излязоха от вчера (08.10):")
    assert "AMD: RS линия 95.2% от 52-седмичния максимум < 97% (вчера: структурен стоп 19.1% > 10%)" in t and "VLO: база с дълбочина 37.4% (над 35%) (вчера: структурен стоп" in t, (name, t[:300])
    print(f"  ✓ {name}: «{t[:230]}…»")
bmon = copy.deepcopy(b); bmon["date"] = "2026-10-12"; bmon["watchlist_exits"] = {**info, "from": "2026-10-09"}
with contextlib.redirect_stdout(io.StringIO()):
    pm = render.render_dashboard(bmon)
assert "Излязоха от предишния бриф (09.10):" in pm
bnone = copy.deepcopy(b); bnone["watchlist_exits"] = {"from": "2026-10-08", "rows": []}
with contextlib.redirect_stdout(io.StringIO()):
    pn = render.render_dashboard(bnone)
assert "Излязоха от вчера (08.10):" in pn and "няма" in txt(pn, "Излязоха от вчера (08.10):")[:60]
bold = copy.deepcopy(B05)
with contextlib.redirect_stdout(io.StringIO()):
    po, mo = render.render_dashboard(bold), render.render_email(bold)
assert "Излязоха от" not in po and "Излязоха от" not in mo
print("  ✓ понеделник → «предишния бриф (09.10)»; без излезли → «няма»; стар бриф без ключа — без реда (страница и имейл)")

print()
print("── 4. свързването ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert "watchlist_exits.run(today, action, watchlist, candidates, explain=screener.explain_exits)" in src and '"watchlist_exits": wl_exits' in src
assert src.index("watchlist_exits.run(") > src.index("action, watchlist = apply_hard_rules(") and src.index("watchlist_exits.run(") > src.index("watchlist_expiry.apply_regime_gate_expiry(")
print("  ✓ main.run: след apply_hard_rules и изтичането на regime_gate; brief['watchlist_exits']")
print("\n✅ test_watchlist_exits: всичко мина")
