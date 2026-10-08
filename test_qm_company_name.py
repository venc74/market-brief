"""
Qullamaggie · името на компанията в картите (07.10.2026): идва от ai_brief._verified_company_name през ПРОИЗВОДСТВЕНОТО свързване в main.run (не е празно и не е самият
тикър), с реални тикъри — и в dashboard-а, и в имейла. Тестът е без мрежа (правило 9: реален файл-fixture, не синтетичен отговор).

РЕАЛНО: tests/fixtures/yahoo_info_DOCN_CORT_CRL_2026-10-07.json — истинският yfinance Ticker(t).info за DOCN, CORT, CRL, заснет на живо на 07.10.2026 21:05 (там е записано, че
производствената _verified_company_name върна на живо "DigitalOcean Holdings, Inc.", "Corcept Therapeutics Incorporat", "Charles River Laboratories Inte" — отрязаното е на Yahoo, shortName се реже на
30 знака, виж забележката по-долу); картите DOCN/CORT/CRL от скана към 02.10.2026 (tests/fixtures/qm_frames_2026-10-02.json); базовият бриф е реалният от 05.10.2026.
СИНТЕТИЧНО: само отказите — Yahoo гърми / тикър без име (проверка на мълчаливия fallback: картата няма ред с компания, не се чупи).
Забележка (известно, не се променя тук): Yahoo реже shortName на ~30 знака ("Charles River Laboratories Inte"); същото име се вижда и в Action/GLB/COT. Тестът проверява само prefix-а.
Пускане: python test_qm_company_name.py
"""
import sys, json, ast, copy, types, pathlib, tempfile, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import qm_breakout as q, ai_brief, render, backtest

tmp = tempfile.TemporaryDirectory(prefix="mb_qmn_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(tmp.name) / "docs", pathlib.Path(tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))

YF = json.loads((ROOT / "tests" / "fixtures" / "yahoo_info_DOCN_CORT_CRL_2026-10-07.json").read_text(encoding="utf-8"))
assert sorted(YF["info"]) == ["CORT", "CRL", "DOCN"] and YF["_captured"].startswith("2026-10-07")
for t, i in YF["info"].items():
    assert i.get("shortName") and i.get("longName") and i.get("quoteType") == "EQUITY", t                 # реален отговор: има и двете имена

PREFIX = {"DOCN": "DigitalOcean Holdings", "CORT": "Corcept Therapeutics", "CRL": "Charles River Laboratories"}
MODE = {"fail": False, "empty": False}


class FakeTicker:
    """Връща РЕАЛНИЯ .info от fixture-а (никаква мрежа)."""
    def __init__(self, sym):
        self._sym = sym

    @property
    def info(self):
        if MODE["fail"]:
            raise RuntimeError("Yahoo недостъпен")                                                       # СИНТЕТИЧНО
        if MODE["empty"]:
            return {}                                                                                    # СИНТЕТИЧНО: тикър без име
        return copy.deepcopy(YF["info"][self._sym])


ai_brief.yf = types.SimpleNamespace(Ticker=FakeTicker)
ai_brief._verified_company_name.cache_clear()

# ── 1. производственото свързване в main.run: и скенерът, и EP ползват ai_brief._verified_company_name(t)["name"] ──
tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
WANT = ast.dump(ast.parse('lambda t: ai_brief._verified_company_name(t)["name"]', mode="eval").body)


def kw_of(mod, fn):
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
             and (n.func.value.id, n.func.attr) == (mod, fn)]
    assert len(calls) == 1, (mod, fn, len(calls))
    kws = {k.arg: k.value for k in calls[0].keywords}
    assert "name_lookup" in kws, f"main.run вика {mod}.{fn} без name_lookup — картите ще са без компания"
    return kws["name_lookup"]


node_cards, node_ep = kw_of("qm_breakout", "cards"), kw_of("qm_ep", "run")
assert ast.dump(node_cards) == WANT and ast.dump(node_ep) == WANT, "свързването в main.py се промени — проверете, че името идва от _verified_company_name"
LOOKUP = eval(compile(ast.Expression(node_cards), "<main.py:qm_breakout.cards>", "eval"), {"ai_brief": ai_brief})
print("  ✓ main.run подава на qm_breakout.cards и на qm_ep.run точно lambda t: ai_brief._verified_company_name(t)['name']")

# ── 2. реални карти + реален Yahoo отговор → име, което не е празно и не е тикърът ──
FIX = json.loads((ROOT / "tests" / "fixtures" / "qm_frames_2026-10-02.json").read_text(encoding="utf-8"))
frames = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"])) for t, d in FIX["frames"].items()}
ROWS, _ = q.scan_frames(frames, lead=FIX["lead"], max_dist_adr=2.0)  # РЕАЛНАТА карта DOCN от 02.10 е на 1.17 ADR от нивото; с правилото ≤1 ADR (08.10) не е карта — тук пазим и трите реални карти (старото определение ≤2 ADR) за рендера/книгата
assert sorted(r["ticker"] for r in ROWS) == ["CORT", "CRL", "DOCN"]
CARDS = q.cards(ROWS, name_lookup=LOOKUP)
by = {c["ticker"]: c for c in CARDS}
for t, c in by.items():
    info = YF["info"][t]
    want = ai_brief._best_company_name(info["shortName"], info["longName"])
    assert c["company"] and c["company"] != t and c["company"] == want and c["company"].startswith(PREFIX[t]), (t, c["company"], want)
    lk = ai_brief._verified_company_name(t)
    assert lk["verified"] is True and lk["name"] == c["company"], (t, lk)
print("  ✓ картите (РЕАЛНИ към 02.10) носят: " + "; ".join(f"{t} → {c['company']!r}" for t, c in by.items()))

# ── 3. видимо в dashboard-а и в имейла ──
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B05)
b["qm_breakout"] = copy.deepcopy(CARDS)
b["qm_diag"] = {"universe": 903, "with_history": 892, "leaders": 167, "candidates": 3, "shown": 3, "as_of": FIX["as_of"], "lead_pct": config.QM_LEAD_PCT, "ok": True, "batches": 10, "batches_failed": 0}
b.setdefault("backtest", {})["qm_breakout"] = backtest.get_qm_summary()                                  # празна книга във временна папка
raw = render.render_dashboard(b)
sec = raw[raw.index('<section id="qm">'):raw.index("</section>", raw.index('<section id="qm">'))]
shown = [htmllib.unescape(m) for m in re.findall(r'<div class="qm-company">(.*?)</div>', sec)]
assert shown == [c["company"][:34] for c in CARDS], (shown, [c["company"] for c in CARDS])             # по реда на картите, шаблонът реже на 34
em = htmllib.unescape(render._qm_email_block(b))
for t, c in by.items():
    assert c["company"][:26] in em, (t, "липсва в имейла")                                               # имейлът реже на 26 знака (render._qm_email_block)
print(f"  ✓ dashboard: {shown}; имейл: началото (26 знака) на всички три имена присъства")

# ── 4. мълчаливият fallback е ВИДИМ в теста: без име картата няма ред с компания и нищо не се чупи ──
for mode in ("fail", "empty"):
    MODE.update({"fail": mode == "fail", "empty": mode == "empty"})
    ai_brief._verified_company_name.cache_clear()
    cs = q.cards(ROWS, name_lookup=LOOKUP)
    assert all(c["company"] == c["ticker"] for c in cs), mode                                            # fallback = тикърът
    bb = copy.deepcopy(b); bb["qm_breakout"] = cs
    r2 = render.render_dashboard(bb)
    s2 = r2[r2.index('<section id="qm">'):r2.index("</section>", r2.index('<section id="qm">'))]
    assert 'class="qm-company"' not in s2 and all(f'class="qm-sym">{t}' in s2 for t in by), mode        # картите са, редът с компания го няма
    assert render._qm_email_block(bb)
print("  ✓ при отказ на Yahoo / тикър без име: компанията е тикърът, картите се рендират без ред с компания, без изключение")
MODE.update({"fail": False, "empty": False})
ai_brief._verified_company_name.cache_clear()
print("\n✅ test_qm_company_name: всичко мина")
