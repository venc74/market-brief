"""
COT · обратен залог (08.10.2026, точки 2г + г). Реалните случаи на брифа от 08.10: VLO и DINO са в Watchlist (покупка), а в COT тезата за RBOB Gasoline са "губят" (цена надолу); HSY и MDLZ печелят при Cocoa, но
губят при Sugar No. 11 (захар надолу ↔ какао нагоре); MPC губи при бензина (RBOB надолу), но печели при Corn (царевица надолу). Секциите не се виждаха една друга.
Бележката се сглобява от КОДА (ефектът и движението са на тезата — кодът ги е изчислил от config.COT_MECHANISM_SIGN × посоката на екстремума; причината — от таблицата config.COT_EFFECT_REASON,
механизъм × ефект), в двете посоки (покупка срещу "губи", шорт срещу "печели"); НИЩО НЕ СЕ МАХА — маркира се.

РЕАЛНО: tests/fixtures/cot_opposites_2026-10-08.json — COT тезите (20 пазара) и тикърите в Action/Watchlist/Qullamaggie/Short на брифа от 08.10; tests/fixtures/brief_2026-10-05.json — брифът от 05.10
(EXPD в Watchlist, в COT: "губи" при 2Y, "печели" при 30Y и RBOB). СИНТЕТИЧНО (маркирано): шорт кандидатите, QM карта в конфликт, повредените входове, празните таблици.
Измерване на филтъра за проза (2г): върху единствения бриф в новия формат (08.10) — 43 механизма с проза, 0 глагола с посока (0 противоречия) → филтърът остава само лог.
Пускане: python test_cot_opposites.py
"""
import sys, json, pathlib, copy, contextlib, io
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import cot_opposites as co, cot_theses as ct, render, main as brief_main
from tests import helpers_page

FX = json.loads((ROOT / "tests" / "fixtures" / "cot_opposites_2026-10-08.json").read_text(encoding="utf-8"))
card = lambda t: {"ticker": t}


def fresh():
    return copy.deepcopy(FX["cot"]), [card(t) for t in FX["action"]], [card(t) for t in FX["watchlist"]], [card(t) for t in FX["qm_breakout"]], [card(t) for t in FX["short_candidates"]]


def thesis_ticker(rows, market, ticker):
    for r in rows:
        if r["market"] == market:
            for key in ("direct_thesis", "cross_sector_thesis"):
                for t in r[key]["tickers"]:
                    if t["ticker"] == ticker:
                        return t


print("── 1. таблицата механизъм × ефект → причина ──")
for typ, spec in config.COT_MECHANISM_SIGN.items():
    if typ == "other":
        assert co.reason("other", "gains") is None and co.reason("other", "loses") is None
        continue
    for eff in ("gains", "loses"):
        assert co.reason(typ, eff), (typ, eff)
assert co.reason("tracks_instrument", "gains", "long") and co.reason("tracks_instrument", "loses", "short") and co.reason("няма_такъв", "gains") is None
print(f"  ✓ всеки от {len(config.COT_MECHANISM_SIGN) - 1} механизма има причина и за 'печели', и за 'губи'; 'other' няма; tracks_instrument е по страната (long/short)")

print()
print("── 2. РЕАЛНИЯТ бриф от 08.10 ──")
assert FX["watchlist"] == ["ZBRA", "ANET", "AMD", "VLO", "DINO", "KEYS", "FTNT", "NTAP"] and FX["qm_breakout"] == ["SN", "SANM", "SITM", "CORT"] and FX["action"] == [] and FX["short_candidates"] == []
rows, action, wl, qm, sh = fresh()
d = co.annotate(rows, {"action": action, "watchlist": wl, "qm": qm}, sh)
assert d == {"cards": 2, "theses": 2, "cross_market": 6}, d
notes = {c["ticker"]: c["cot_notes"] for c in wl + qm if c.get("cot_notes")}
assert sorted(notes) == ["DINO", "VLO"], sorted(notes)
n = notes["VLO"][0]
assert n["market"] == "RBOB Gasoline" and n["effect"] == "loses"
assert n["text"] == ("COT: цената на RBOB Gasoline НАДОЛУ → VLO ГУБИ (цена на продукта: по-ниска цена на продукта = по-ниски приходи) — обратно на сетъпа; информация, не отменя нивата."), n["text"]
print("  ✓ карти: VLO и DINO (Watchlist) получават бележка; никоя друга от 8-те Watchlist и 4-те QM карти не е в конфликт")
print("    " + n["text"])
t = thesis_ticker(rows, "RBOB Gasoline", "VLO")["opposite"][0]
assert t == {"where": "Watchlist", "side": "long", "text": "⚠ обратен залог: VLO е кандидат за покупка в Watchlist, а тази теза казва ГУБИ (цена на продукта: по-ниска цена на продукта = по-ниски приходи)."}, t
assert thesis_ticker(rows, "RBOB Gasoline", "DINO")["opposite"][0]["where"] == "Watchlist"
print("  ✓ тезата за RBOB: VLO и DINO носят «⚠ обратен залог … е кандидат за покупка в Watchlist, а тази теза казва ГУБИ …»")
cm = {(r["market"], tk): thesis_ticker(rows, r["market"], tk).get("cross_market") for r in rows for tk in ("HSY", "MDLZ", "MPC") if thesis_ticker(rows, r["market"], tk)}
assert sorted(k for k, v in cm.items() if v) == sorted([("Corn", "MPC"), ("Cocoa", "HSY"), ("Cocoa", "MDLZ"), ("RBOB Gasoline", "MPC"), ("Sugar No. 11", "HSY"), ("Sugar No. 11", "MDLZ")])
assert cm[("Cocoa", "HSY")] == ["⚠ обратни сигнали: HSY ПЕЧЕЛИ — цената на Sugar No. 11 НАДОЛУ (разход за суровина: по-ниска цена на суровината = по-ниски разходи)"], cm[("Cocoa", "HSY")]
assert cm[("Sugar No. 11", "HSY")][0].startswith("⚠ обратни сигнали: HSY ГУБИ — цената на Cocoa НАГОРЕ (разход за суровина: по-висока цена")
assert cm[("RBOB Gasoline", "MPC")][0].startswith("⚠ обратни сигнали: MPC ПЕЧЕЛИ — цената на Corn НАДОЛУ") and cm[("Corn", "MPC")][0].startswith("⚠ обратни сигнали: MPC ГУБИ — цената на RBOB Gasoline НАДОЛУ")
print("  ✓ между пазарите: HSY и MDLZ (Sugar ↔ Cocoa) и MPC (RBOB ↔ Corn) се маркират и в двете тези, с причината на другата; нищо не е махнато")
print("    " + cm[("Cocoa", "HSY")][0])
rows2, *_ = fresh()
assert [t["ticker"] for r in rows2 for key in ("direct_thesis", "cross_sector_thesis") for t in r[key]["tickers"]] == [t["ticker"] for r in rows for key in ("direct_thesis", "cross_sector_thesis") for t in r[key]["tickers"]]
print("  ✓ списъците с тикъри в тезите са същите като преди анотацията — само добавени полета")

print()
print("── 3. в двете посоки и граници (СИНТЕТИЧНИ карти върху РЕАЛНИТЕ тези) ──")
rows, action, wl, qm, sh = fresh()
sh = [card("MPC"), card("VLO"), card("AAPL")]                                                                         # шорт: MPC "печели" при Corn (конфликт), VLO "губи" при RBOB (съгласуван)
act, qmc = [card("MPC")], [card("DINO")]
d = co.annotate(rows, {"watchlist": wl, "qm": qmc, "action": act}, sh)
byt = lambda lst, tk: next(c for c in lst if c["ticker"] == tk)
assert [x["market"] for x in byt(sh, "MPC")["cot_notes"]] == ["Corn"] and byt(sh, "MPC")["cot_notes"][0]["effect"] == "gains"      # шорт срещу "печели"
assert "cot_notes" not in byt(sh, "VLO") and "cot_notes" not in byt(sh, "AAPL")                                                # шорт на тикър, който COT казва, че губи → без бележка
assert [x["market"] for x in byt(act, "MPC")["cot_notes"]] == ["RBOB Gasoline"]                                              # покупка срещу "губи"
assert byt(wl, "VLO")["cot_notes"] and byt(qmc, "DINO")["cot_notes"][0]["market"] == "RBOB Gasoline"
mpc_corn = thesis_ticker(rows, "Corn", "MPC")["opposite"]
assert [(o["where"], o["side"]) for o in mpc_corn] == [("Short", "short")] and "кандидат за шорт в Short" in mpc_corn[0]["text"]
mpc_rbob = thesis_ticker(rows, "RBOB Gasoline", "MPC")["opposite"]
assert [(o["where"], o["side"]) for o in mpc_rbob] == [("Action", "long")]
print("  ✓ шорт срещу 'печели' → бележка (MPC/Corn); шорт на 'губи' → без; покупка в Action срещу 'губи' → бележка (MPC/RBOB); QM карта на DINO → бележка")
qm_c = [card("VLO")]
co.annotate(rows, {"qm": qm_c}, [])
assert qm_c[0]["cot_notes"][0]["market"] == "RBOB Gasoline"
rows3 = fresh()[0]
c_stale = [{"ticker": "ZBRA", "cot_notes": [{"stale": True}]}]
co.annotate(rows3, {"watchlist": c_stale}, [])
assert "cot_notes" not in c_stale[0]
print("  ✓ СИНТЕТИЧНО: остаряла бележка върху карта без конфликт се изчиства (идемпотентно)")
bad_rows = [None, {"market": "X"}, {"market": "Y", "direct_thesis": {"tickers": [None, "AAA", {"ticker": None, "effect": "gains"}, {"ticker": "BBB", "effect": "gains", "mechanisms": [{"type": "няма"}]}]}}]
with contextlib.redirect_stdout(io.StringIO()):
    dd = co.annotate(bad_rows, {"watchlist": [{"ticker": "BBB"}, None, {}]}, None)
    dn = co.annotate(None, None, None)
assert dd == {"cards": 0, "theses": 0, "cross_market": 0} and dn == {"cards": 0, "theses": 0, "cross_market": 0}
print("  ✓ СИНТЕТИЧНО: повредени редове/тикъри/карти/None → без изключение и без бележки")

print()
print("── 4. РЕАЛНИЯТ бриф от 05.10 през страницата и имейла (EXPD: Watchlist срещу COT 'губи' при 2Y) ──")
brief, LV = helpers_page.build_brief()
assert [w["ticker"] for w in brief["watchlist"]] == ["EXPD"]
with contextlib.redirect_stdout(io.StringIO()):
    dg = co.annotate(brief["cot"], {"action": brief["action"], "watchlist": brief["watchlist"], "qm": brief["qm_breakout"]}, brief.get("short_candidates"))
expd = brief["watchlist"][0]
assert expd["cot_notes"] and any(x["market"] == "2-Year Treasury Note" and x["effect"] == "loses" for x in expd["cot_notes"]), expd.get("cot_notes")
page = render.render_dashboard(brief)
assert "обратно на сетъпа; информация, не отменя нивата" in page and 'class="cot-note"' in page and "EXPD ГУБИ" in page
assert "⚠ обратен залог: EXPD е кандидат за покупка в Watchlist" in page and "⚠ обратни сигнали: EXPD" in page
print(f"  ✓ страницата: бележка върху картата на EXPD ({len(expd['cot_notes'])} COT тези), «⚠ обратен залог …» и «⚠ обратни сигнали …» в COT секцията; диагностика {dg}")
syn = [{"market": "Test", "move_text": "цената на Test НАДОЛУ", "direct_thesis": {"tickers": []},
        "cross_sector_thesis": {"tickers": [{"ticker": "EXEL", "effect": "loses", "mechanisms": [{"type": "output_price"}]}]}}]            # СИНТЕТИЧНА теза, която е против РЕАЛНАТА Action карта на EXEL
co.annotate(syn, {"action": brief["action"]}, [])
email = render.render_email(brief)
assert "COT: цената на Test НАДОЛУ → EXEL ГУБИ" in email and "обратно на сетъпа" in email
print("  ✓ имейлът: СИНТЕТИЧНА теза срещу РЕАЛНАТА Action карта на EXEL → бележката е под плана на картата")
print()
print("── 5. свързване в main.run ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
i_ann, i_short, i_brief = src.index("cot_opposites.annotate(cot_with_theses"), src.index("short_candidates = short_screener.run_short_screen"), src.index('"cot": cot_with_theses')
i_qm, i_track = src.index("qm_cards = qm_breakout.cards("), src.index("backtest.update_backtest_tracker(action, today")
assert i_short < i_ann < i_brief and i_qm < i_ann and i_ann < i_track
print("  ✓ анотацията е СЛЕД QM картите и шорт кандидатите, ПРЕДИ записа в Track Record и ПРЕДИ сглобяването на брифа; в try/except (бележките са информация)")
print("\n✅ test_cot_opposites: всичко мина")
