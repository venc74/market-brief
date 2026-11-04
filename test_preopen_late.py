"""
04.11.2026 · четвърти преглед, Н6: закъсняло пускане на обновяването преди отварянето (стартира след 09:30 Ню Йорк, преди config.PREOPEN_LATE_UNTIL_NY) → каре „Обновяване преди
отварянето днес няма: …“ и data/preopen/<дата>.json с late True — до 04.11 само ::notice:: в лога, а страницата не казваше нищо (не личеше дали е вървяло).
Другото пускане по графика (10:05 Ню Йорк) и 08:05 — както досега (без каре); вече успешно обновяване не се презаписва.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — рамката на страницата (като сутрешен бриф на деня).
СИНТЕТИЧНО (означено): часовете на пускане (09:41 / 10:05 / 08:05 Ню Йорк на 04.11.2026), успешният JSON в т. 3.
Пускане: python test_preopen_late.py
"""
import sys, json, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_prelate_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
(config.DATA_DIR / "2026-11-04.json").write_text(json.dumps(B19), encoding="utf-8")
ny = lambda h, m: dt.datetime(2026, 11, 4, h + 5, m, tzinfo=dt.timezone.utc)      # СИНТЕТИЧНО: EST = UTC−5
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. late_reason ──")
assert preopen.late_reason(ny(9, 41)) == "пускането стартира в 09:41 Ню Йорк — след отварянето; премаркетът не е проверен днес"
assert preopen.late_reason(ny(10, 5)) is None and preopen.late_reason(ny(8, 5)) is None and preopen.late_reason(ny(9, 5)) is None
assert preopen.late_reason(dt.datetime(2026, 11, 26, 14, 40, tzinfo=dt.timezone.utc)) is None       # Thanksgiving — няма сесия
print("  ✓ 09:41 — закъсняло; 08:05 / 09:05 / 10:05 и ден без сесия — не")

print("── 2. main в 09:41 → каре и JSON, без имейл ──")
with q():
    assert preopen.main(ny(9, 41)) == 0
saved = json.loads((config.DATA_DIR / "preopen" / "2026-11-04.json").read_text(encoding="utf-8"))
assert saved["late"] is True and saved["ok"] is False and saved["email"] == {"sent": False}
page = (config.DOCS_DIR / "index.html").read_text(encoding="utf-8")
assert "Обновяване преди отварянето днес няма: пускането стартира в 09:41 Ню Йорк — след отварянето; премаркетът не е проверен днес." in page
print("  ✓ карето: „Обновяване преди отварянето днес няма …“")

print("── 3. вече успешно обновяване → не се презаписва; 10:05 → нищо ──")
(config.DATA_DIR / "preopen" / "2026-11-04.json").write_text(json.dumps({"ok": True, "date": "2026-11-04", "late": False}), encoding="utf-8")
(config.DOCS_DIR / "index.html").unlink()
with q():
    preopen.main(ny(9, 50)); preopen.main(ny(10, 5))
assert json.loads((config.DATA_DIR / "preopen" / "2026-11-04.json").read_text(encoding="utf-8")) == {"ok": True, "date": "2026-11-04", "late": False}
assert not (config.DOCS_DIR / "index.html").exists()
print("  ✓")
print("\n✅ test_preopen_late: всичко мина")
