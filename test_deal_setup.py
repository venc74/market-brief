"""
26.10.2026 · етап 4б, т. 1 (решение от 26.10): ЦЕЛ НА ПРИДОБИВАНЕ НЕ Е СЕТЪП — при маркер „цел на придобиване“ setup.kind "deal": без buy-stop, план, Action и AI текст; текст
„Сделка — цената следва условията, не е сетъп.“; живите записи в книгите на такъв тикър получават етикет "deal".

Случаят (РЕАЛЕН): ROKU на 23.10 — маркерът „цел на придобиване (Fox Corporation, обявено 14.06.2026)“ е на картата, а сетъпът е "confirmed", eligible, „купува се до $167.88“; от Action
я спираше само моделът. Маркерът идваше след класификацията (стъпката spinoff е след AI и твърдите правила) — сега целите сред кандидатите се търсят преди нея (main: стъпка merger_pre),
а списъците с подавания от EDGAR се споделят с проверката на картите (subs). Записът ROKU_2026-10-20_buystop (задействан на 22.10 по $159.89) получава етикет "deal".

РЕАЛНО: tests/fixtures/deal_roku_2026-10-23.json — картите на ROKU от 23.10 и 26.10 и записът му в buy-stop книгата; tests/fixtures/edgar_8k_merger_2026-10-21.json — реалният 8-K на ROKU
(т. 1.01) и редовете от submissions; tests/fixtures/brief_2026-10-19.json — реалният бриф за рендера. СИНТЕТИЧНО (означено): класификацията "Action" от модела, подмененото теглене от EDGAR,
вмъкването на картата в брифа от 19.10.
Пускане: python test_deal_setup.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_deal_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import setup_rules, spinoff_watch as sw, backtest, render, ai_brief, watchlist_exits
from src import main
backtest._TRACKER_PATH = config.DATA_DIR / "backtest_tracker.json"
assert not str(backtest._TRACKER_PATH.resolve()).startswith(str((ROOT / "data").resolve()))
q = lambda: contextlib.redirect_stdout(io.StringIO())

FX = json.loads((ROOT / "tests" / "fixtures" / "deal_roku_2026-10-23.json").read_text(encoding="utf-8"))
MG = json.loads((ROOT / "tests" / "fixtures" / "edgar_8k_merger_2026-10-21.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
REC = FX["record"]["rec"]

print("── 1. картата на ROKU от 23.10: по цената — confirmed; с маркера — сделка ──")
raw = copy.deepcopy(FX["card_2026_10_23"])
assert raw["setup"]["kind"] == "confirmed" and raw["setup"]["eligible"] and "купува се до $167.88" in raw["setup"]["trigger_text"]       # какво показа брифът от 23.10
assert raw["merger_target"]["buyer"] == "Fox Corporation"
for k in ("setup", "ai", "plan", "plan_preview", "levels"):
    raw.pop(k, None)
c = copy.deepcopy(raw)
setup_rules.annotate([c], dt.date(2026, 10, 23), {"ROKU": REC})
s = c["setup"]
assert s["kind"] == "deal" and s["eligible"] is False and s["gate"] == "deal" and s["price_kind"] == "confirmed"
assert s["buy_stop"] is None and s["max_chase"] is None and s["stop"] is None and s["valid_through"] is None
assert s["trigger_text"] == setup_rules.DEAL_TEXT == "Сделка — цената следва условията, не е сетъп."
assert s["deal"] == {"buyer": "Fox Corporation", "announced": "2026-06-14", "filing_date": "2026-06-15"}
assert s["book_note"] == "в buy-stop книгата: отворена от 22.10 по $159.89" and not s.get("triggered")           # задействаният запис — само неутрален ред
plain = copy.deepcopy(raw); plain.pop("merger_target")
setup_rules.annotate([plain], dt.date(2026, 10, 23))
assert plain["setup"]["kind"] == "confirmed" and "купува се до $167.88" in plain["setup"]["trigger_text"]           # без маркера — както на 23.10
print(f"  ✓ без маркера: {plain['setup']['trigger_text'][:70]}…; с маркера: kind deal (по цената — confirmed), без buy-stop / стоп / таван, «{s['trigger_text']}»")

print()
print("── 2. AI текст не се иска; твърдите правила: Watchlist, без план; компактен ред ──")
sent = []
real_call = ai_brief._call_claude
ai_brief._call_claude = lambda system, user, **k: (sent.append(user), '{"tickers": []}')[1]                        # СИНТЕТИЧНО
try:
    with q():
        ai_brief.ticker_narratives([c], [], "Defensive")
finally:
    ai_brief._call_claude = real_call
assert sent == []                                                                                                   # сетъпът "deal" е извън AI_NARRATIVE_SETUPS
cc = copy.deepcopy(c); cc["ai"] = {"classification": "Action", "why_now": "…"}                                       # СИНТЕТИЧНО: моделът казва Action
config.ENABLE_BACKTEST = False
with q():
    act, wl = main.apply_hard_rules([cc], 0.5, "Offensive")
assert act == [] and [x["ticker"] for x in wl] == ["ROKU"]
w = wl[0]
assert w["ai"]["watchlist_reason_type"] == "technical_gate" and w["ai"]["watchlist_trigger"] == setup_rules.DEAL_TEXT
assert "plan" not in w and "plan_preview" not in w and "levels" not in w
cards, compact = render.split_watchlist(wl)
assert cards == [] and compact[0]["kind"] == "deal" and compact[0]["merger"]["buyer"] == "Fox Corporation"
assert compact[0]["reason"] == "сделка — цената следва условията, не е сетъп; в buy-stop книгата: отворена от 22.10 по $159.89"
assert watchlist_exits.setup_text(s) == "сделка — цената следва условията, не е сетъп"
b = copy.deepcopy(B19); b["watchlist"] = [w] + b["watchlist"]                                                       # СИНТЕТИЧНО: картата в брифа от 19.10
with q():
    flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", h)))
    page, mail = flat(render.render_dashboard(b, publish=False)), flat(render.render_email(b))
row = "ROKU — сделка — цената следва условията, не е сетъп; в buy-stop книгата: отворена от 22.10 по $159.89, отчет 02.11, ⚠ цел на придобиване (Fox Corporation, 14.06.2026)"
assert row in page and row in mail
print("  ✓ без AI извикване; Action от модела → Watchlist (technical_gate), без план / нива; ред „без сетъп“: «" + row[:110] + "…» (страница и имейл)")

print()
print("── 3. проверката преди класификацията: EDGAR веднъж на run (subs) ──")
SUB = MG["roku_submissions"]
ROKU_DOC = next(d for d in MG["docs"] if d["ticker"] == "ROKU")
calls = []
def get(url):                                                                                                        # СИНТЕТИЧНО теглене върху РЕАЛНИТЕ документи
    calls.append(url)
    if "submissions" in url:
        return json.dumps(SUB)
    if url.endswith("index.json"):
        return json.dumps({"directory": {"item": []}})
    return ROKU_DOC["text"] if ROKU_DOC["accession"].replace("-", "") in url else ""
subs = {}
with q():
    sw.check(["ROKU"], today=dt.date(2026, 10, 23), get=get, cik_map={"ROKU": SUB["cik"]}, merger_tickers=["ROKU"], subs=subs)
    pre = dict(sw.LAST_MERGERS)
    n1 = sum("submissions" in u for u in calls)
    sw.check(["ROKU", "AAPL"], today=dt.date(2026, 10, 23), get=get, cik_map={"ROKU": SUB["cik"]}, merger_tickers=["ROKU"], subs=subs)
assert pre["ROKU"]["buyer"] == "Fox Corporation" and n1 == 1 and sum("submissions" in u for u in calls) == 1 and sw.LAST_MERGERS["ROKU"]["buyer"] == "Fox Corporation"
fresh = copy.deepcopy(raw); fresh.pop("merger_target")
assert sw.annotate_mergers([[fresh]], pre) == 1
setup_rules.annotate([fresh], dt.date(2026, 10, 23))
assert fresh["setup"]["kind"] == "deal"
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i_pre, i_cls, i_ai = src.index('steps.step("merger_pre"'), src.index("candidates = setup_rules.annotate(candidates"), src.index('narratives = steps.step("narratives"')
assert i_pre < i_cls < i_ai and "subs=edgar_subs" in src[src.index("def _spinoff():"):]
print("  ✓ списъкът с подавания на ROKU — теглен веднъж за двете проверки; стъпката merger_pre е преди класификацията и AI")

print()
print("── 4. етикетът \"deal\" върху живия запис (РЕАЛНИЯТ ROKU_2026-10-20_buystop) и в книгата ──")
backtest._save_tracker({FX["record"]["key"]: copy.deepcopy(REC)})
with q():
    assert backtest.apply_deal_labels(pre, dt.date(2026, 10, 26)) == 1
    assert backtest.apply_deal_labels(pre, dt.date(2026, 10, 27)) == 0 and backtest.apply_deal_labels({}, dt.date(2026, 10, 27)) == 0     # веднъж; провал на EDGAR не маха
t = backtest._load_tracker()
assert t[FX["record"]["key"]]["deal"] == {"buyer": "Fox Corporation", "announced": "2026-06-14", "filing_date": "2026-06-15", "seen": "2026-10-26"}
with q():
    bs = backtest.get_buystop_summary()
live = [r for r in bs.get("live", []) if r["ticker"] == "ROKU"]
assert live and live[0]["deal"]["buyer"] == "Fox Corporation"
b2 = copy.deepcopy(B19); b2.setdefault("backtest", {})["buystop"] = bs
with q():
    page2 = flat(render.render_dashboard(b2, publish=False))
assert "deal · цел на придобиване (Fox Corporation, 14.06.2026) — резултатът следва условията на сделката" in page2
src_bt = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert src_bt.index("backtest.apply_deal_labels(spinoff_watch.LAST_MERGERS") > src_bt.index("backtest.update_backtest_tracker(")
print("  ✓ записът получава deal {Fox Corporation, 14.06.2026, видян 26.10}; таблицата на buy-stop книгата: «deal · цел на придобиване (Fox Corporation, 14.06.2026) …»")
print("\n✅ test_deal_setup: всичко мина")
