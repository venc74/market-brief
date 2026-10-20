"""
20.10.2026 · етап 3б, т. 4: замразен речник на езиковия филтър. ai_brief._bg_vocab() строи речника от публикуваните брифове в docs/data/ — до 20.10 изходът на езиковия филтър в
25 теста зависеше от реалните docs/data/ (растат всеки ден). Сега run_tests.py дава BG_VOCAB_FILE = tests/fixtures/bg_vocab_2026-10-20.json; production (без BG_VOCAB_FILE) строи
речника от docs/data/ както досега.

РЕАЛНО: tests/fixtures/bg_vocab_2026-10-20.json (речникът от 89-те публикувани брифа 14.06–20.10, бот commit 8559b89); tests/fixtures/brief_2026-10-05.json и brief_2026-10-09.json
(реални брифове — копирани във временна docs/data/ за пътя без BG_VOCAB_FILE).
Пускане: python test_bg_vocab_fixture.py (през run_tests — с BG_VOCAB_FILE; директно — без него, пътят от docs/data/ е във временна папка)
"""
import sys, json, pathlib, tempfile, shutil, importlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src import ai_brief

FIX = json.loads((ROOT / "tests" / "fixtures" / "bg_vocab_2026-10-20.json").read_text(encoding="utf-8"))
assert FIX["source"] == {"files": 89, "first": "2026-06-14", "last": "2026-10-20", "commit": "8559b89"}

print("── 1. от файла (BG_VOCAB_FILE) ──")
config.BG_VOCAB_FILE = str(ROOT / "tests" / "fixtures" / "bg_vocab_2026-10-20.json")
ai_brief._bg_vocab.cache_clear()
cyr, lat = ai_brief._bg_vocab()
assert cyr == FIX["cyr"] and lat == FIX["lat"] and len(cyr) == 11206 and len(lat) == 3554
print(f"  ✓ {len(cyr)} кирилски и {len(lat)} латински думи — точно замразеният речник")

print()
print("── 2. без BG_VOCAB_FILE — от docs/data/ (временна папка с два РЕАЛНИ брифа) ──")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="mb_vocab_"))
(tmp / "data").mkdir()
for d in ("2026-10-05", "2026-10-09"):
    shutil.copy(ROOT / "tests" / "fixtures" / f"brief_{d}.json", tmp / "data" / f"{d}.json")
config.BG_VOCAB_FILE, config.DOCS_DIR = "", tmp
ai_brief._bg_vocab.cache_clear()
cyr2, lat2 = ai_brief._bg_vocab()
assert cyr2 and all(FIX["cyr"].get(w, 0) >= n for w, n in cyr2.items())          # двата брифа са подмножество на 89-те
print(f"  ✓ {len(cyr2)} думи от двата брифа; всяка е в замразения речник поне толкова пъти")
shutil.rmtree(tmp)
ai_brief._bg_vocab.cache_clear()
print("\n✅ test_bg_vocab_fixture: всичко мина")
