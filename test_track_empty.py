"""
Пакет 2 (2026-10-05) · Track Record v2 без нито една резолвирана сделка не показва "Win rate: 0.0% (0 win / 0 loss)" — а "Още няма затворени сделки по v2".

РЕАЛНО: брифът от 05.10.2026 (първият след превключването v1 → v2: total_resolved 0, v1 архив n=51) — старият вид на редовете е записан в tests/fixtures/
brief_2026-10-05.json (backtest-блокът) и се рендерира с шаблона; брифът от 02.10 (v2 с резолюции няма още — затова случаят с резолюции е СИНТЕТИЧЕН:
копие на блока с total_resolved/wins/losses зададени от теста).
Пускане: python test_track_empty.py
"""
import sys, json, pathlib, tempfile, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import render

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
bt = B05["backtest"]
assert bt["total_resolved"] == 0 and bt["wins"] == 0 and bt["losses"] == 0 and bt["v1_archive"]["n"] == 51


def page(brief):
    with tempfile.TemporaryDirectory() as docs, tempfile.TemporaryDirectory() as data:
        o1, o2 = config.DOCS_DIR, config.DATA_DIR
        config.DOCS_DIR, config.DATA_DIR = pathlib.Path(docs), pathlib.Path(data)
        try:
            html = htmllib.unescape(render.render_dashboard(brief))
            return " ".join(re.sub(r"<[^>]+>", "", html).split())                      # видимият текст
        finally:
            config.DOCS_DIR, config.DATA_DIR = o1, o2


print("── РЕАЛНО 05.10: още няма резолюции по v2 ──")
p = page(B05)
sec = p.split("Track Record v2 ·")[1].split("</section>")[0]
assert "Още няма затворени сделки по v2 — win rate и среден R се показват от първата резолюция." in sec
assert "Win rate: 0" not in sec and "0 win / 0 loss" not in sec and "Среден реализиран R" not in sec and "expired-in-trail" not in sec
assert "Все още отворени: 0 (преди цел 1) + 0 (след частична продажба на цел 1, trailing)" in sec and "Чакат buy-stop: 0 · не се задействаха: 0" in sec
assert "v1 методология: n=51, win rate 25.5%" in sec                                      # архивният ред за v1 остава
print("  ✓ вместо 'Win rate: 0.0% (0 win / 0 loss)' → 'Още няма затворени сделки по v2…'; няма редовете за стоп/trailing/R; редовете за отворени и чакащи buy-stop остават; v1 архивът остава")

print()
print("── със резолюции (СИНТЕТИЧНО) ──")
b2 = json.loads(json.dumps(B05))
b2["backtest"].update(total_resolved=4, wins=3, losses=1, win_rate_pct=75.0, avg_realized_r=1.2, stopped=1, trailing_stop_exit=2, expired=1)
sec2 = page(b2).split("Track Record v2 ·")[1].split("</section>")[0]
assert "Win rate: 75.0% (3 win / 1 loss)" in sec2 and "Среден реализиран R: 1.2" in sec2 and "Още няма затворени сделки" not in sec2
print("  ✓ при total_resolved > 0 редовете са както преди (Win rate 75.0% (3 win / 1 loss), среден R)")
print()
print("Всички тестове минаха.")
