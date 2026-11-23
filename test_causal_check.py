"""
18.11.2026 (спешно, т. 3): затягане на макро разказа (AI).
  • Причинни думи и глаголи („заради“, „поради“, „след като“, „в резултат“, „X скочи от Y“, „изстреляха“, „което вдигна“) — само когато ЕДНО подадено заглавие съдържа и
    причината, и следствието (src/causal_check.py); иначе изречението пада. Реално 18.11: „Иранските удари по американски бази в Залива изстреляха VIX …“ — заглавието за Иран
    няма VIX; „… 10-годишната доходност добави +12.0 б.п. …, което вдигна MOVE …“ — нито едно заглавие не свързва доходността с MOVE.
  • Посоката на RS на секторите (sector_claims.rs_direction_check) — срещу RS за 4 седм. сега / преди 5 сесии. Реално 16.11: „водещите сектори — Здравеопазване, Финанси,
    Потребителски … — устояха на нощния натиск и запазиха относителна сила“ при XLP 14.3 → 6.6, XLV 14.6 → 8.1, XLF 10.6 → 6.9.
  • Отчетът — ai_macro["drops_report"]: колко изречения паднаха и защо (в данните, не на страницата).
Измерено върху 111 разказа (13.06–18.11, 746 изречения): причинни твърдения 30, махнати 7 (2 — 18.11); посока на RS — 12 твърдения, махнати 2 (13.11, 16.11).

РЕАЛНО: tests/fixtures/macro_causal_2026-11.json — разказите, новините, крипто заглавията и секторната карта от брифовете на 16–18.11.
СИНТЕТИЧНО (означено): изреченията в т. 3 и т. 5, заглавието-опора в т. 3, отговорът на модела в т. 6.
Пускане: python test_causal_check.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, json, copy, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import causal_check as cc, sector_claims as sc, ai_brief as ab

FX = json.loads((ROOT / "tests" / "fixtures" / "macro_causal_2026-11.json").read_text(encoding="utf-8"))["briefs"]
B18, B17, B16 = FX["2026-11-18"], FX["2026-11-17"], FX["2026-11-16"]
rows = lambda b: b["board"]["sectors"] + b["board"]["subsectors"]

print("── 1. РЕАЛНО: 18.11 — двете причинни изречения падат, „За нас“ остава ──")
new, rem = cc.check(B18["macro_brief"], B18["news"], crypto=B18["crypto"])
assert [r["marker"] for r in rem] == ["изстреляха", "вдигна"], rem
assert rem[0]["why"].startswith("нито едно заглавие не свързва") and "VIX" in rem[0]["why"] and "MOVE" in rem[1]["why"]
assert new.startswith("За нас: водещите ни сектори") and new.count(".") >= 1
assert cc.check(B18["macro_brief"], B18["news"], verbs=False, crypto=B18["crypto"])[1] == []        # само думите — 18.11 без промяна
print(f"  ✓ махнати 2: «{rem[0]['sentence'][:60]}…», «…{rem[1]['sentence'][-60:]}»")

print("── 2. РЕАЛНО: 17.11 (14 изречения) и 16.11 — нищо не пада ──")
assert cc.check(B17["macro_brief"], B17["news"], crypto=B17["crypto"])[1] == []
assert cc.check(B16["macro_brief"], B16["news"], crypto=B16["crypto"])[1] == []
print("  ✓ без махнати")

print("── 3. СИНТЕТИЧНО: „VIX скочи от иранските удари“ — пада без заглавие, остава със заглавие за двете ──")
s = "VIX скочи от иранските удари по американски бази и стигна 25.46."
assert cc.check(s, B18["news"])[1][0]["kind"] == "„от“"
assert cc.check(s, [{"headline": "Wall Street's fear gauge VIX jumps as Iran strikes U.S. bases"}])[1] == []             # СИНТЕТИЧНО заглавие
assert cc.check("Доходността е на 5.12%, след като за 5 сесии добави 25.7 б.п.", [])[1] == []           # същият подлог — не е връзка
assert cc.check("Петролът се срина с 8% за 5 сесии.", [])[1] == [] and cc.check("CoreWeave вдигна guidance.", [])[1] == []
assert cc.check("VIX падна от 25 до 19.", [])[1] == [] and cc.check("Fed Net Liquidity падна от $5960B до $5840B.", [])[1] == []
print("  ✓ „от“ с причина — пада; със заглавие — остава; „след като“ със същия подлог, „се срина“, „вдигна guidance“, „падна от 25“ — не са причина")

print("── 4. РЕАЛНО: посоката на RS — 16.11 пада, 18.11 („държат … над +8%“) остава ──")
new16, rd16 = sc.rs_direction_check(B16["macro_brief"], rows(B16))
assert len(rd16) == 1 and rd16[0]["claim"] == "задържа" and set(rd16[0]["etfs"]) >= {"XLV", "XLF", "XLP"} and "запазиха относителна сила" in rd16[0]["sentence"], rd16
assert sc.rs_direction_check(B18["macro_brief"], rows(B18))[1] == []
print(f"  ✓ 16.11: {rd16[0]['why'][:110]}…")

print("── 5. СИНТЕТИЧНО: „водещите сектори продължават да укрепват RS“ при числата на 18.11 ──")
p = sc.rs_direction_problem("За нас: водещите сектори продължават да укрепват RS спрямо SPY.", rows(B18))
assert p and p["claim"] == "нагоре" and len(p["etfs"]) == 7 and p["changes"]["XLV"] == -7.34, p
assert sc.rs_direction_problem("Полупроводниците губят RS.", rows(B18)) is None                      # SMH −14.7 → −11.6: расте, но RS е отрицателна — „губят“ като ниво е вярно
assert sc.rs_direction_problem("Полупроводниците набират RS.", rows(B18)) is None                      # расте — вярно
assert sc.rs_direction_problem("Индустрията губи RS.", rows(B18)) is None                              # XLI 3.78 → 3.71 — в мъртвата зона
assert sc.rs_direction_problem("Комуналните губят RS.", [dict(etf="XLU", rs_4w=8.9, rs_4w_prev=6.0)])["claim"] == "надолу"   # СИНТЕТИЧНО: ръст и положителна
assert sc.rs_direction_problem("Водещите държат RS, а tech губят тегло.", rows(B18)) is None              # две посоки — не се приписва
print("  ✓ „укрепват“ при 6 от 7 надолу — пада; две посоки — не се пипа")

print("── 6. СИНТЕТИЧНО: в macro_and_sector_brief — проверките и отчетът ──")
orig = (ab._macro_and_sector_brief_ai, ab.check_narrative_numbers)
ab._macro_and_sector_brief_ai = lambda *a, **k: {"macro_brief": B18["macro_brief"]}
ab.check_narrative_numbers = lambda text, vals, dates=None: (text, [])          # СИНТЕТИЧНО: входът тук е празен — числата се проверяват в test_narrative_numbers
try:
    with contextlib.redirect_stdout(io.StringIO()):
        out = ab.macro_and_sector_brief({}, [], {"indicators": []}, news=B18["news"], crypto=B18["crypto"], board=B18["board"])
finally:
    ab._macro_and_sector_brief_ai, ab.check_narrative_numbers = orig
assert len(out["causal_drops"]) == 2 and out["drops_report"]["by_reason"].get("причинна връзка без опора в едно заглавие") == 2, out.get("drops_report")
assert out["macro_brief"].startswith("За нас:")
assert "ПОСОКАТА НА RS НА СЕКТОРИТЕ" in ab.macro_user_prompt({}, [], {"indicators": []}, board=B18["board"]) and ab.rs_direction_block(None) == ""
print(f"  ✓ drops_report: {out['drops_report']}")
print("\n✅ test_causal_check: всичко мина")
