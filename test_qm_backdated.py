"""
04.11.2026 · прегледът: записите със задна дата в книгата qm_breakout остават, с етикет „записан със задна дата (след поправка ДД.ММ)“. Такъв запис се ражда, когато 5-минутните бари скъсят
предишния запис на тикъра и стара карта престане да е продължение. Симулация върху копие на реалния tracker с реалните 5-минутни бари (04.11): само един — SN от картата на 12.10.

РЕАЛНО: tests/fixtures/preopen_pending_2026-11-04.json (SN 09.10 преди и след барите, SN 12.10); tests/fixtures/brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): картата в временния snapshot; записът след резолюцията в т. 3 носи стойностите от симулацията (вход $186.75, стоп на 14.10, −1 R, реални 5-минутни бари от 04.11).
Пускане: python test_qm_backdated.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_backdated_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, render

FX = json.loads((ROOT / "tests" / "fixtures" / "preopen_pending_2026-11-04.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
K9, K12 = "SN_2026-10-09_qm", "SN_2026-10-12_qm"
q = lambda: contextlib.redirect_stdout(io.StringIO())
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

print("── 1. кога е „със задна дата“ ──")
new = {k: v for k, v in FX["sn_1012"].items() if k != "backdated"}
t = {K9: FX["sn_0910_after"], K12: copy.deepcopy(new)}
with q():
    backtest._stamp_backdated(t, {K9}, "2026-11-05")
assert t[K12]["backdated"] == {"created": "2026-11-05"}
t = {K9: FX["sn_0910_before"], K12: copy.deepcopy(new)}                                  # преди барите предишният запис свършва на 16.10 и не е по 5-минутни бари
with q():
    backtest._stamp_backdated(t, {K9}, "2026-11-05")
assert "backdated" not in t[K12]
t = {K9: FX["sn_0910_after"], K12: {**new, "entry_date": "2026-11-05"}}                  # картата от днес — обикновен запис
with q():
    backtest._stamp_backdated(t, {K9}, "2026-11-05")
assert "backdated" not in t[K12]
print("  ✓ стара карта + предишен запис, скъсен от 5-минутните бари → етикет; без тази причина или с карта от днес — без етикет")

print()
print("── 2. през ingest-а: новият запис и роденият на 04.11 (СИНТЕТИЧНО: картата в snapshot-а) ──")
card = {"ticker": "SN", "trigger": 193.68, "adr": 3.4, "close": 190.0, "signal_date": "2026-10-13"}
(config.DATA_DIR / "2026-10-20.json").write_text(json.dumps({"date": "2026-10-20", "qm_breakout": [card], "thermometer": {"regime": "Defensive"}}, ensure_ascii=False), encoding="utf-8")
t = {K9: copy.deepcopy(FX["sn_0910_after"]), K12: copy.deepcopy(new)}
assert "backdated" not in t[K12]
t[K12].update(status="stopped", fill_date="2026-10-12", fill_price=186.75, stop_loss=184.57, exit_date="2026-10-14", resolution_date="2026-10-14", realized_r=-1.0, how="stop", r_basis="5m")   # от симулацията
with q():
    backtest._ingest_new_positions(t, None, "2026-11-05")
assert t[K12]["backdated"] == {"created": "2026-11-04"}                                  # роденият преди етикета — с датата си
assert t["SN_2026-10-20_qm"]["backdated"] == {"created": "2026-11-05"}
with q():
    backtest._ingest_new_positions(t, None, "2026-11-06")
assert t[K12]["backdated"] == {"created": "2026-11-04"} and t["SN_2026-10-20_qm"]["backdated"] == {"created": "2026-11-05"}          # идемпотентно
(config.DATA_DIR / "2026-10-20.json").unlink()
print("  ✓ SN 12.10 — „след поправка 04.11“; нов запис през ingest-а — с датата на записа; второто пускане не го сменя")

print()
print("── 3. само един запис: картата от 14.10 е в живота на SN 12.10 ──")
closed12 = {**new, "status": "stopped", "fill_date": "2026-10-12", "fill_price": 186.75, "stop_loss": 184.57, "exit_date": "2026-10-14", "resolution_date": "2026-10-14", "realized_r": -1.0, "how": "stop", "r_basis": "5m"}
assert backtest._is_continuation({K12: closed12}, "SN", "2026-10-14", backtest.CATEGORY_QM) is True
print("  ✓ SN 12.10: стоп на 14.10 → картата от 14.10 е продължение, нов запис няма")

print()
print("── 4. книгата на страницата ──")
config.TRACK_QM = True
backtest_load = backtest._load_tracker
for rec, where in ((closed12, "Последни затворени"), (new, "Чакащи и отворени")):
    r = {**rec, "backdated": {"created": "2026-11-04"}}
    backtest._load_tracker = lambda r=r: {K12: r}
    try:
        with q():
            S = backtest.get_qm_summary()
    finally:
        backtest._load_tracker = backtest_load
    assert (S["recent"] or S["live"])[0]["backdated"] == {"created": "2026-11-04"}
    b = copy.deepcopy(B19); b.setdefault("backtest", {})["qm_breakout"] = S
    with q():
        page = flat(render.render_dashboard(b, publish=False))
    i = page.index(where, page.index("Измерване — книга qm_breakout"))
    assert "SN" in page[i:i + 700] and "записан със задна дата (след поправка 04.11)" in page[i:i + 700], page[i:i + 400]
with q():
    assert "записан със задна дата" not in render.render_dashboard(copy.deepcopy(B19), publish=False)
print("  ✓ етикетът е и при чакащите / отворените, и при затворените; записът остава в статистиката; стар бриф — без него")
print("\n✅ test_qm_backdated: всичко мина")
