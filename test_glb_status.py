"""
С3 (втори преглед, 10.10.2026) · провал на GLB скрийнъра не е тих: статус (glb_screener.LAST_STATUS / brief["glb_status"]) → банер в data_warnings и ред в секцията.

До 10.10: при провал main ловеше изключението, glb_candidates = [], секцията изчезваше (шаблонът я крие при празен списък), LAST_WISH_SIGNALS оставаше [] — книгата "GLB по Уиш"
губеше деня тихо (сигналът е "свеж пробив на последния цял бар" — утре вече не е свеж). "Не се изпълни" и "няма кандидати" изглеждаха еднакво.

РЕАЛНО: tests/fixtures/brief_2026-10-05.json (страницата, в която се рендерира секцията). СИНТЕТИЧНО: паднало yf.download (и частично паднало), празният списък,
подмененото изключение в main.
Пускане: python test_glb_status.py
"""
import sys, json, pathlib, tempfile, copy, html as htmllib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_glbst_")
config.DOCS_DIR, config.DATA_DIR = pathlib.Path(_tmp.name) / "docs", pathlib.Path(_tmp.name) / "data"
config.DOCS_DIR.mkdir(); config.DATA_DIR.mkdir()
from src import glb_screener as g, data_warnings, render

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
STATE = config.DATA_DIR / "glb_state.json"
g.time.sleep = lambda s: None


def screen_with(download):
    g.yf.download = download
    with contextlib.redirect_stdout(io.StringIO()):
        out = g.screen(universe=["AAA", "BBB", "CCC"], batch_size=2, state_path=STATE, today="2026-10-12")
    return out, dict(g.LAST_STATUS)


def boom(*a, **k):
    raise RuntimeError("YFRateLimitError: Too Many Requests (СИНТЕТИЧНО)")


print("── 1. статусът на screen() ──")
out, st = screen_with(boom)
assert out == [] and st["ok"] is False and st["batches"] == 2 and st["batches_failed"] == 2 and st["with_history"] == 0 and g.LAST_WISH_SIGNALS == []
calls = {"n": 0}


def half(batch, **k):                                               # първата партида пада, втората връща празни/кратки данни
    calls["n"] += 1
    if calls["n"] == 1:
        raise RuntimeError("timeout (СИНТЕТИЧНО)")
    idx = pd.date_range("2026-09-01", periods=30, freq="B")
    s = pd.Series(range(30), index=idx, dtype=float) + 10
    return pd.DataFrame({"Open": s, "High": s + 1, "Low": s - 1, "Close": s, "Volume": 1e6})
out, st2 = screen_with(half)
assert st2["ok"] is True and st2["batches_failed"] == 1 and st2["with_history"] == 1 and st2["universe"] == 3
print("  ✓ всички партиди паднали → ok False, 2/2 паднали, 0 тикъра с история, книгата без сигнали; една от две паднала → ok True, batches_failed 1, with_history 1")

print()
print("── 2. банерът ──")
w = data_warnings.collect(None, None, glb_status=st)
assert len(w) == 1 and w[0]["source"] == "glb" and "НЕ значи, че няма GLB кандидати" in w[0]["message"] and f"„{config.GLB_CLOSE_BOOK_NAME}“ не получи сигнали" in w[0]["message"] and "по Уиш" not in w[0]["message"]
w2 = data_warnings.collect(None, None, glb_status=st2)
assert len(w2) == 1 and "1 от 2 партиди" in w2[0]["message"] and "върху 1 от 3 тикъра" in w2[0]["message"]
ok0 = {"ok": True, "error": None, "universe": 903, "batches": 19, "batches_failed": 0, "with_history": 901, "candidates": 0, "wish_signals": 0}
assert data_warnings.collect(None, None, glb_status=ok0) == [] and data_warnings.collect(None, None) == []
print("  ✓ провал → банер (празният списък не значи 'няма кандидати'; книгата на Уиш не получи сигнали); частичен → банер с броя; изпълнен с 0 кандидати → без банер")

print()
print("── 3. секцията в РЕАЛНАТА страница от 05.10 ──")


def page(**kw):
    b = copy.deepcopy(B05); b["glb_candidates"] = []; b.update(kw)
    return " ".join(htmllib.unescape(render.render_dashboard(b)).split())


h_fail = page(glb_status=st, data_warnings=data_warnings.collect(None, None, glb_status=st))
assert "GLB Watchlist · Green Line Breakout" in h_fail and "Скрийнърът не се изпълни днес (Yahoo не върна ценови данни)" in h_fail
h_none = page(glb_status=ok0)
assert "Няма GLB кандидати днес — проверени 901 от 903 тикъра." in h_none and "не се изпълни" not in h_none
h_old = page()                                                        # стар бриф без glb_status и с празен списък — както преди: без секция
assert "GLB Watchlist · Green Line Breakout" not in h_old
h_full = " ".join(htmllib.unescape(render.render_dashboard(copy.deepcopy(B05) | {"glb_status": ok0 | {"candidates": 5}})).split())
assert "Няма GLB кандидати днес" not in h_full and "ADI" in h_full
print("  ✓ провал → секцията стои с '⚠ Скрийнърът не се изпълни днес (…)'; изпълнен без кандидати → 'Няма GLB кандидати днес — проверени 901 от 903'; стар бриф → както преди; с кандидати → картите")

print()
print("── 4. main: изключение → статус ──")
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'glb_screener.LAST_STATUS = {"ok": False, "error": f"{type(e).__name__}: {e}"}' in src
assert "glb_status=(glb_screener.LAST_STATUS if config.ENABLE_GLB_SCREENER else None)" in src and '"glb_status": dict(glb_screener.LAST_STATUS)' in src
print("  ✓ main слага ok False при изключение в screen(), подава статуса на data_warnings и го записва в брифа")
print()
print("Всички тестове минаха.")
