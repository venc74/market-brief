"""
21.10.2026 · етап 4, ритъм на данните (решение от 21.10): COT секцията е цялата само в първия бриф след нов отчет на CFTC; в другите дни — един ред
„COT: без нови данни — отчет към ДД.ММ, следващ отчет петък ДД.ММ (публикуван 21:30 Берлин)“ и секцията е свита. Отчетът е към вторника и излиза в петък в 15:30 ET
(21:30 Берлин; 20:30, докато САЩ и ЕС не са сменили часа заедно). Стари данни, пропуснат петък или липсващ предишен бриф → цялата секция, както досега.

РЕАЛНО: tests/fixtures/brief_2026-10-09 / 12 / 14 / 15 / 16 / 19.json — cot_status на истинските брифове (отчети към 29.09, 06.10, 13.10).
СИНТЕТИЧНО (означено): статусът „стари данни“, датите за смяната на часа и празника (календарни сметки, не данни).
Пускане: python test_cot_rhythm.py
"""
import sys, json, pathlib, tempfile, shutil, copy, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config

_tmp = tempfile.TemporaryDirectory(prefix="mb_cotr_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import data_rhythm as r, render

FX = ROOT / "tests" / "fixtures"
DAYS = ["2026-10-09", "2026-10-12", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19"]
B = {d: json.loads((FX / f"brief_{d}.json").read_text(encoding="utf-8")) for d in DAYS}
for d in DAYS:
    shutil.copy(FX / f"brief_{d}.json", config.DATA_DIR / f"{d}.json")

print("── 1. последователността на реалните брифове ──")
got = {d: r.cot_rhythm(B[d]["cot_status"], r.previous_brief(d), d) for d in DAYS}
assert r.previous_brief("2026-10-14")["date"] == "2026-10-12" and r.previous_brief("2026-10-09") is None
assert {d: g["compact"] for d, g in got.items()} == {"2026-10-09": False, "2026-10-12": False, "2026-10-14": True, "2026-10-15": True, "2026-10-16": True, "2026-10-19": False}
assert got["2026-10-12"]["fresh"] and got["2026-10-12"]["text"] is None and got["2026-10-19"]["fresh"] and got["2026-10-19"]["text"] is None
assert got["2026-10-14"]["text"] == "COT: без нови данни — отчет към 06.10, следващ отчет петък 16.10 (публикуван 21:30 Берлин)"
assert got["2026-10-16"]["text"] == got["2026-10-14"]["text"] and not got["2026-10-16"]["late"]          # петъчният бриф (07:30) е преди отчета вечерта
print("  ✓ 09.10 (няма предишен бриф) и 12.10, 19.10 (нов отчет) — цялата секция без ред; 14–16.10 — „без нови данни — отчет към 06.10, следващ отчет петък 16.10 (публикуван 21:30 Берлин)“")

print()
print("── 2. стари данни, пропуснат петък, смяна на часа, празник (СИНТЕТИЧНИ входове) ──")
assert r.cot_rhythm({**B["2026-10-16"]["cot_status"], "stale": True}, B["2026-10-15"], "2026-10-16")["compact"] is False
late = r.cot_rhythm(B["2026-10-16"]["cot_status"], B["2026-10-16"], "2026-10-19")
assert late["compact"] is False and late["late"] and late["text"] == "COT: отчетът, публикуван в петък 16.10, още не е в данните — показан е отчетът към 06.10"
assert r.cftc_next_release("2026-10-20")["release_berlin"] == "20:30" and r.cftc_next_release("2026-10-27")["release_berlin"] == "21:30"   # ЕС сменя на 25.10, САЩ — на 01.11
assert r.cftc_next_release("2026-03-03")["release_berlin"] == "20:30" and r.cftc_next_release("2026-03-24")["release_berlin"] == "21:30"
h = r.cot_rhythm({"as_of": "2026-12-15"}, {"cot_status": {"as_of": "2026-12-15"}}, "2026-12-28")
assert h["compact"] and "петък 25.12 е празник в САЩ" in h["text"] and not h["late"]
assert r.cot_rhythm(None, None, "2026-10-21") == {"compact": False, "fresh": False, "as_of": None, "text": None}
print("  ✓ стари данни → цялата секция (банерът ѝ); отчетът от петък липсва в понеделник → цялата секция и ред „още не е в данните“; 30.10 — 20:30 Берлин, 06.11 — 21:30; 25.12 — празник")

print()
print("── 3. страницата (РЕАЛНИТЕ брифове от 14.10 и 12.10) ──")
q = lambda: contextlib.redirect_stdout(io.StringIO())
b14 = copy.deepcopy(B["2026-10-14"]); b14["cot_rhythm"] = got["2026-10-14"]
b12 = copy.deepcopy(B["2026-10-12"]); b12["cot_rhythm"] = got["2026-10-12"]
with q():
    p14, p12, p_old = render.render_dashboard(b14), render.render_dashboard(b12), render.render_dashboard(copy.deepcopy(B["2026-10-14"]))
s14 = p14[p14.index("COT Екстремуми"):]; s14 = s14[:s14.index("</section>")]
assert "COT: без нови данни — отчет към 06.10, следващ отчет петък 16.10 (публикуван 21:30 Берлин)" in s14 and '<details class="cot-full">' in s14 and s14.count("</details>") >= 1
assert s14.index("без нови данни") < s14.index('<details class="cot-full">') < s14.index('class="thesis ')
s12 = p12[p12.index("COT Екстремуми"):]; s12 = s12[:s12.index("</section>")]
assert "без нови данни" not in s12 and "cot-full" not in s12 and 'class="thesis ' in s12
assert "cot-full" not in p_old                                                         # стар бриф без полето — както досега
print("  ✓ 14.10: редът и свитата секция; 12.10: цялата секция без ред; бриф без полето — както досега")
print("\n✅ test_cot_rhythm: всичко мина")
