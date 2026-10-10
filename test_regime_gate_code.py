"""
В2 (втори преглед, 10.10.2026) · "regime_gate" (10-сесийното изтичане от Watchlist) се решава от КОДА, не от AI етикета.

До 10.10: моделът слагаше watchlist_reason_type "regime_gate" и на карти, които кодът е класифицирал като below_pivot/too_wide; watchlist_expiry пускаше 10-дневен брояч
(календарни дни, config казва "работни") и в Defensive махаше картата; на следващия ден "other" я връщаше. "Излязоха от вчера" показваше "в скрийнъра, но извън 10-те карти",
а buy-stop книгата се захранваше СЛЕД изтичането — т.е. AI етикетът решаваше кои кандидати се измерват.
РЕАЛНИ казуси (data/watchlist_expiry.json на 10.10, вградено тук — тестовете не четат data/): ZBRA {first_seen 2026-09-29, expiry 2026-10-09} — too_wide, етикет regime_gate 05–08.10,
other на 09.10; EXPD {first_seen 2026-10-09, expiry 2026-10-19} — below_pivot с жив запис EXPD_2026-10-09_buystop, етикет regime_gate на 09.10.

РЕАЛНО: картата на ZBRA (tests/fixtures/watchlist_cards_2026-10-08.json, с публикувания AI етикет regime_gate), картата на EXPD (tests/fixtures/brief_2026-10-05.json),
състоянието по-горе. СИНТЕТИЧНО (маркирано): AI етикетът regime_gate върху картата на EXPD от 05.10 (реалният етикет е от 09.10), датите в бъдещето (19.10), потвърденият
сетъп в т.3, предишният Watchlist в т.3.
Пускане: python test_regime_gate_code.py
"""
import sys, json, pathlib, copy, tempfile, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
config.ENABLE_BACKTEST = False
from src import main as brief_main, watchlist_expiry, watchlist_exits

FX08 = json.loads((ROOT / "tests" / "fixtures" / "watchlist_cards_2026-10-08.json").read_text(encoding="utf-8"))
B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
ZBRA = next(c for c in FX08["cards"] if c["ticker"] == "ZBRA")
EXPD = next(c for c in B05["watchlist"] if c["ticker"] == "EXPD")
REAL_STATE = {"ZBRA": {"first_seen_date": "2026-09-29", "expiry_date": "2026-10-09", "expired": False},
              "EXPD": {"first_seen_date": "2026-10-09", "expiry_date": "2026-10-19", "expired": False}}
assert ZBRA["setup"]["kind"] == "too_wide" and ZBRA["ai_published"]["watchlist_reason_type"] == "regime_gate" and EXPD["setup"]["kind"] == "below_pivot"

tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_rg_"))
watchlist_expiry._STATE_PATH = tmp / "watchlist_expiry.json"
config.DATA_DIR = tmp


def card(base, ai_reason):
    c = copy.deepcopy(base); c.pop("ai_published", None)
    c.update({"sector": "Technology", "company": c["ticker"], "ai": {"classification": "Watchlist", "watchlist_reason_type": ai_reason, "why_now": "x"}})
    return c


print("── 1. КОНТРОЛ: старият път (AI етикетът стига до изтичането) маха двете реални карти след срока ──")
watchlist_expiry._STATE_PATH.write_text(json.dumps(REAL_STATE))
old_style = [card(ZBRA, "regime_gate"), card(EXPD, "regime_gate")]          # етикетът на модела, БЕЗ apply_hard_rules (както изтичането го виждаше до 10.10)
with contextlib.redirect_stdout(io.StringIO()):
    kept = watchlist_expiry.apply_regime_gate_expiry(old_style, "Defensive", "2026-10-26")    # СИНТЕТИЧНА дата след срока и в сесии (09.10 + 10 сесии = 23.10)
assert [c["ticker"] for c in kept] == []
print("  ✓ с AI етикета regime_gate и двете реални карти изчезват в Defensive (ZBRA too_wide, EXPD below_pivot с жив buy-stop запис)")

print()
print("── 2. новият път: apply_hard_rules дава етикета от кода → изтичането не ги пипа и изчиства старите броячи ──")
watchlist_expiry._STATE_PATH.write_text(json.dumps(REAL_STATE))
with contextlib.redirect_stdout(io.StringIO()):
    _, watch = brief_main.apply_hard_rules([card(ZBRA, "regime_gate"), card(EXPD, "regime_gate")], 0.5, "Defensive")
reasons = {c["ticker"]: (c["ai"]["watchlist_reason_type"], c["ai"].get("watchlist_reason_type_ai")) for c in watch}
assert reasons == {"ZBRA": ("technical_gate", "regime_gate"), "EXPD": ("technical_gate", "regime_gate")}, reasons
with contextlib.redirect_stdout(io.StringIO()):
    kept = watchlist_expiry.apply_regime_gate_expiry(watch, "Defensive", "2026-10-26")
assert {c["ticker"] for c in kept} == {"ZBRA", "EXPD"} and json.loads(watchlist_expiry._STATE_PATH.read_text()) == {} and watchlist_expiry.LAST_EXPIRED == {}
print("  ✓ ZBRA/EXPD → technical_gate (AI етикетът остава само в watchlist_reason_type_ai); на 26.10 в Defensive и двете остават;"
      " реалните броячи (ZBRA до 09.10, EXPD до 19.10) са изчистени")

print()
print("── 3. потвърден сетъп, спрян от режима → regime_gate от кода → изтича след 10 сесии; «Излязоха от вчера» казва защо ──")
watchlist_expiry._STATE_PATH.write_text("{}")
conf = card(EXPD, "other")                                                         # СИНТЕТИЧНО: потвърден пробив, AI казва "other"
conf["setup"] = {**conf["setup"], "kind": "confirmed", "eligible": True}
conf.update({"pct_from_pivot": 4.0, "breakout_volume": True, "volume_ratio": 1.8})   # +4% над pivot → entry timing не е "good" → Defensive блокира
assert brief_main._regime_gate(conf, "Defensive")
with contextlib.redirect_stdout(io.StringIO()):
    _, watch = brief_main.apply_hard_rules([conf], 0.5, "Defensive")
assert watch[0]["ai"]["watchlist_reason_type"] == "regime_gate"
d0 = watchlist_expiry.apply_regime_gate_expiry(watch, "Defensive", "2026-10-12")
exp = watchlist_expiry._expiry_for("2026-10-12")
assert exp == "2026-10-26" and [c["ticker"] for c in d0] == ["EXPD"]             # 12.10 + 10 сесии (13…23.10) → 26.10 (сесия № 11)
d_before = watchlist_expiry.apply_regime_gate_expiry(watch, "Defensive", "2026-10-23")
assert [c["ticker"] for c in d_before] == ["EXPD"]
with contextlib.redirect_stdout(io.StringIO()):
    d_n = watchlist_expiry.apply_regime_gate_expiry(watch, "Defensive", exp)
assert d_n == [] and set(watchlist_expiry.LAST_EXPIRED) == {"EXPD"}
rows = watchlist_exits.compute([{"ticker": "EXPD", "setup": conf["setup"]}], [], d_n, [conf], expired=watchlist_expiry.LAST_EXPIRED)
assert rows[0]["kind"] == "expired" and rows[0]["reason"].startswith("изтекъл прозорец за промяна в режима (10 сесии от 2026-10-12")
assert "извън 10-те карти" not in rows[0]["reason"]
print(f"  ✓ потвърден сетъп (+4% над pivot) в Defensive → regime_gate от кода; срок {exp} (10 NYSE сесии), на 23.10 още е тук, на {exp} изтича;"
      f" «Излязоха»: «{rows[0]['reason']}» (до 10.10: «в скрийнъра, но извън 10-те карти»)")
with contextlib.redirect_stdout(io.StringIO()):
    _, w_off = brief_main.apply_hard_rules([copy.deepcopy(conf) | {"ai": {"classification": "Watchlist", "why_now": "x"}}], 1.0, "Offensive")
assert not w_off or w_off[0]["ai"]["watchlist_reason_type"] != "regime_gate"
print("  ✓ същият сетъп в Offensive → не е regime_gate (режимът не го спира)")

print()
print("── 4. buy-stop книгата се захранва ПРЕДИ изтичането ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i_before = src.index("watchlist_before_expiry = list(watchlist)")
i_expiry = src.index("watchlist = watchlist_expiry.apply_regime_gate_expiry(")
assert i_before < i_expiry and "backtest.update_backtest_tracker(action, today, watchlist_before_expiry," in src
print("  ✓ main.py: книгата получава Watchlist-а отпреди изтичането (watchlist_before_expiry), не филтрирания")
print()
print("Всички тестове минаха.")
