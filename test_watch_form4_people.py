"""
10.11.2026 (т. 5): Form 4 за наблюдаваните —
  (а) флаг „продава ≥25% от дела си“ от кода, независимо от 10b5-1 (watch_monitor.big_sellers; дялът — по сметки за прозореца);
  (б) AI не пише „рутинно“, когато флагът е вдигнат (подсказка + проверка в кода: ai_brief.strip_routine);
  (в) CLUSTER и таблицата — по хора: редовете обединени по човек и ден (CRCL 10.11: 54 реда от 4 души → 5 реда).

РЕАЛНО: tests/fixtures/watch_form4_2026-11-10.json (наблюдаваните от брифа на 10.11 — CRCL, TDOC, AI, ACN — и ELF от 04.11, с AI текста от брифа),
tests/fixtures/brief_2026-10-19.json (рамката на страницата).
СИНТЕТИЧНО (означено): т. 2 — ред без „след сделката“; т. 4 — кратък AI отговор за тикър без флаг.
Пускане: python test_watch_form4_people.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_f4people_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import watch_monitor as wm, ai_brief, render

FXD = ROOT / "tests" / "fixtures"
FX = json.loads((FXD / "watch_form4_2026-11-10.json").read_text(encoding="utf-8"))
B19 = json.loads((FXD / "brief_2026-10-19.json").read_text(encoding="utf-8"))
W = {r["ticker"]: r for r in FX["watch_2026_11_10"]}
ELF = FX["watch_elf_2026_11_04"][0]
for r in list(W.values()) + [ELF]:                                                  # както collect() (новите полета)
    r["insider_days"], r["insider_big_sell"] = wm.person_days(r["insider"]), wm.big_sellers(r["insider"])

print("── 1. РЕАЛНО: CRCL 10.11 — 54 реда, 4 души → 5 реда по човек и ден ──")
c = W["CRCL"]
assert len(c["insider"]) == 54 and len({t["owner_name"] for t in c["insider"]}) == 4
assert c["insider_flags"][0]["n"] == 54 and c["insider_flags"][0]["owners"] == 4 and c["insider_flags"][0]["cluster"]
D = [(d["date"], d["owner_title"], d["n"], round(d["value"]), d["pct_of_holdings"]) for d in c["insider_days"]]
assert D == [("2026-11-05", "Chairman and CEO", 50, 4264269, 12.1), ("2026-11-03", "Chief Financial Officer", 1, 309628, 1.4),
             ("2026-11-03", "Chief Commercial Officer", 1, 133773, 0.3), ("2026-11-03", "Chief Accounting Officer", 1, 87234, 1.3),
             ("2026-10-21", "Chief Financial Officer", 1, 1350000, 4.7)], D
assert round(sum(d["value"] for d in c["insider_days"])) == round(sum(t["value"] for t in c["insider"]))       # сумите не се губят
assert c["insider_big_sell"] == []
print("  ✓ " + "; ".join(f"{d[1]} {d[0][8:10]}.{d[0][5:7]} ×{d[2]} = ${d[3]:,} ({d[4]}%)" for d in D))

print("── 2. дялът по сметки ──")
assert wm.stake_sold_pct([t for t in ELF["insider"] if t["owner_name"] == "AMIN TARANG"]) == 25.9            # РЕАЛНО: 12.7% + 13.8% + 1.5% от реда → 25.9% от дела
assert [b["pct"] for b in ELF["insider_big_sell"]] == [25.9]
assert wm.stake_sold_pct([t for t in W["ACN"]["insider"] if t["owner_name"] == "Sekido Ryoji"]) == 83.0     # РЕАЛНО: 7 038 → 1 194 в два реда (67.4% и 48.0%)
assert wm.stake_sold_pct([{**ELF["insider"][0], "shares_after": None}]) is None and wm.stake_sold_pct([]) is None   # СИНТЕТИЧНО: без „след“ → не знаем
B = {t: [(b["title"], b["pct"], b["planned_10b5_1"]) for b in W[t]["insider_big_sell"]] for t in ("TDOC", "AI", "ACN")}
assert B == {"TDOC": [("President, International", 45.5, True)], "AI": [("CEO and Chairman of the Board", 37.6, True)],
             "ACN": [("Co-CEO Asia Pacific", 83.0, False), ("Co-CEO Asia Pacific", 62.5, True)]}, B
T = wm.big_sell_text(W["TDOC"]["insider_big_sell"][0])
assert T == "продава ≥25% от дела си: President, International — 45.5% ($270,774, 06.11; по план 10b5-1)", T
print(f"  ✓ ELF 25.9% (три реда под 25%); ACN Sekido 83%; флаг: TDOC, AI, ACN ×2 — и по 10b5-1\n  ✓ {T}")

print("── 3. „рутин…“ при вдигнат флаг — РЕАЛНИТЕ текстове от 10.11 ──")
for t in ("TDOC", "AI"):
    txt = W[t]["ai"]["insider_read"]
    assert re.search("рутин", txt)
    out, gone = ai_brief.strip_routine(txt)
    assert gone and not re.search("рутин", out, re.I) and out, (t, out)
    print(f"  ✓ {t}: махнато «{gone[0]['removed'][:70]}…»; остава «{out[:70]}…»")

print("── 4. AI групата: подсказката по хора и проверката в кода ──")
sent = {}
def fake(system, user, max_tokens=0, **k):
    sent["user"] = user
    return json.dumps({"digests": [{"ticker": t, "summary": "", "insider_read": W[t]["ai"]["insider_read"], "cross_reference": ""} for t in ("TDOC", "AI", "CRCL")]
                      + [{"ticker": "ACN", "summary": "", "insider_read": "Продажбите на COO са по план. Те са рутинни.", "cross_reference": ""}]}, ensure_ascii=False)   # СИНТЕТИЧНО (ACN)
ai_brief._call_claude, _orig = fake, ai_brief._call_claude
try:
    with contextlib.redirect_stdout(io.StringIO()) as log:
        got = {a["ticker"]: a for a in ai_brief._watch_digest_batch([W[t] for t in ("TDOC", "AI", "CRCL", "ACN")], {}, 72)}
finally:
    ai_brief._call_claude = _orig
U = sent["user"]
payload = json.loads(U[U.index("["):U.index("\n\nТЕМИ")])
pc = next(p for p in payload if p["ticker"] == "CRCL")
assert len(pc["insider"]) == 5 and pc["insider"][0]["form4_rows"] == 50 and pc["insider_flags"][0]["people"] == 4 and pc["insider_flags"][0]["form4_rows"] == 54
assert next(p for p in payload if p["ticker"] == "TDOC")["sells_25pct_of_stake"] == [{"title": "President, International", "pct_of_stake": 45.5, "planned_10b5_1": True}]
assert "Казвай броя хора, НЕ броя" in U and "НЕ пиши „рутинно“" in U
for t in ("TDOC", "AI", "ACN"):
    assert not re.search("рутин", got[t]["ai"]["insider_read"], re.I) and any(x["term"] == "рутин" for x in got[t]["ai_removed"]), t
assert got["ACN"]["ai"]["insider_read"] == "Продажбите на COO са по план."
assert "рутинни по подразбиране" in got["CRCL"]["ai"]["insider_read"]                                       # без флаг — текстът остава
assert "при продажба ≥25% от дела — махнато" in log.getvalue()
print("  ✓ към AI: CRCL 5 реда (50 Form 4 реда в един), people 4; TDOC с sells_25pct_of_stake; „рутин…“ махнато при TDOC, AI, ACN; CRCL — непокътнат")

print("── 5. страницата ──")
bb = copy.deepcopy(B19); bb["watch"] = [W[t] for t in ("CRCL", "TDOC")]
with contextlib.redirect_stdout(io.StringIO()):
    page = render.render_dashboard(bb, publish=False)
assert "CLUSTER продажби · 4 души · по план (10b5-1)" in page and "CLUSTER продажби 54" not in page
assert "(50 сделки)" in page and page.count("Chief Financial Officer") >= 2
assert "⚠ ≥25% от дела · 46%" in page and "⚠ " + T + " — Form 4, независимо от 10b5-1" in page
src = (ROOT / "src" / "watch_monitor.py").read_text(encoding="utf-8")
assert '"insider_days": person_days(txns)' in src and '"insider_big_sell": big_sellers(txns)' in src
old = copy.deepcopy(W["CRCL"]); old.pop("insider_days"); old.pop("insider_big_sell")                         # стар бриф — без новите полета
bb["watch"] = [old]
with contextlib.redirect_stdout(io.StringIO()):
    assert "Allaire Jeremy" in render.render_dashboard(bb, publish=False)
print("  ✓ CLUSTER с хора; таблицата по човек и ден със сделките в скоби; ⚠ ≥25% на реда и в разгънатото; стар бриф — суровите редове")
print("\n✅ test_watch_form4_people: всичко мина")
