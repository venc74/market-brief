"""
Пакет 2 (2026-10-05) · вчерашният watchlist_trigger се филтрира спрямо текущите v2 позиции: текст за позиция ("Вече в портфейла от …", "управлявай
съществуващата позиция") се подава на модела само ако днес има ЖИВА v2 позиция за тикъра (и датата в текста е нейната). След превключването v1 → v2 на 05.10
архивираните v1 позиции вече не са живи — иначе AMD, AVT, ANET получаваха "вече в портфейла / не добавяй" ден след ден.

РЕАЛНО: Watchlist картите с вчерашните trigger-и от брифа на 02.10.2026 (предишният snapshot за run-а на 05.10): AVT (позиция от 14.09), AMD (22.09), ANET (05.08) са
"existing_position"; KEYS, NTAP, FTNT, ZBRA са нормални trigger-и; tracker-ът на v2 е празен на 05.10 (брифът: switched_on 2026-10-05, open_positions []).
СИНТЕТИЧНО: живите v2 позиции в другите случаи (позиция със съвпадаща и несъвпадаща дата), подменената директория data/.
Пускане: python test_prior_triggers.py
"""
import sys, json, pathlib, io, contextlib, tempfile, shutil, re
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief

FIX = ROOT / "tests" / "fixtures"
B02 = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
CARDS = {w["ticker"]: w for w in B02["watchlist"]}
assert B05["backtest"]["methodology"]["switched_on"] == "2026-10-05" and B05["backtest"]["open_positions"] == []
assert [CARDS[t]["ai"]["watchlist_reason_type"] for t in ("AVT", "AMD", "ANET")] == ["existing_position"] * 3

tmp = tempfile.TemporaryDirectory(prefix="mb_prior_")
shutil.copy(FIX / "brief_2026-10-02.json", pathlib.Path(tmp.name) / "2026-10-02.json")          # РЕАЛНИЯТ предишен snapshot
orig_dir = config.DATA_DIR
config.DATA_DIR = pathlib.Path(tmp.name)


def load(live, today="2026-10-05"):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ai_brief._load_prior_watchlist_triggers(today, live)
    return out, buf.getvalue()


print("── след превключването: няма живи v2 позиции ──")
out, log = load({})
assert set(out) == {"KEYS", "NTAP", "FTNT", "ZBRA"}, set(out)                                  # AVT, AMD, ANET са махнати
for t in ("AVT", "AMD", "ANET"):
    assert f"вчерашният trigger за {t} не се подава на модела — вчерашният текст е за позиция, която не е жива v2 позиция днес" in log
assert out["FTNT"] == CARDS["FTNT"]["ai"]["watchlist_trigger"] and out["ZBRA"] == CARDS["ZBRA"]["ai"]["watchlist_trigger"]            # нормалните остават непроменени
print("  ✓ РЕАЛНО: AVT (позиция от 14.09), AMD (22.09), ANET (05.08) не се подават — по ред в лога; KEYS, NTAP, FTNT, ZBRA (обикновени trigger-и) се подават непроменени")

print()
print("── жива v2 позиция ──")
live = {"AMD": {"ticker": "AMD", "status": "open", "method": "v2", "fill_date": "2026-09-22", "entry_date": "2026-09-22"}}                 # СИНТЕТИЧНО: AMD е жива v2 позиция със същата дата
out, log = load(live)
assert "AMD" in out and "AVT" not in out and "ANET" not in out
live2 = {"AMD": {"ticker": "AMD", "status": "open", "method": "v2", "fill_date": "2026-10-06", "entry_date": "2026-10-06"}}              # жива v2 позиция, но с ДРУГА дата от текста (v1 текст)
out, log = load(live2)
assert "AMD" not in out and "датата на позицията във вчерашния текст (2026-09-22) не е на жива v2 позиция" in log
print("  ✓ СИНТЕТИЧНО: AMD е жива v2 позиция с датата от текста → текстът се подава; жива v2 позиция с друга дата (текстът е за стара v1 позиция) → не се подава")

print()
print("── граници ──")
assert ai_brief.prior_trigger_usable("XYZ", {"ai": {"watchlist_trigger": "Пробив над $10 с обем"}}, {})[0] is True
assert ai_brief.prior_trigger_usable("XYZ", {"ai": {"watchlist_trigger": "Управлявай съществуващата позиция"}}, {})[0] is False
assert ai_brief.prior_trigger_usable("XYZ", {"ai": {"watchlist_reason_type": "existing_position", "watchlist_trigger": "нещо"}}, {})[0] is False
assert ai_brief.prior_trigger_usable("XYZ", {"ai": {"watchlist_trigger": "Вече в портфейла от 2026-10-01"}}, {"XYZ": {"fill_date": "2026-10-01"}})[0] is True
assert ai_brief.prior_trigger_usable("XYZ", {"ai": {"watchlist_trigger": "Вече в портфейла"}}, {"XYZ": {"fill_date": "2026-10-01"}})[0] is True      # без дата в текста — жива позиция стига
assert ai_brief.prior_trigger_usable("XYZ", {"ai": {"watchlist_trigger": None}}, {})[0] is True
print("  ✓ обикновен trigger → годен; текст/тип за позиция без жива позиция → не; жива с еднаква дата → да; без дата в текста → да; празен → да (няма какво да се подаде)")

print()
print("── през ticker_narratives: какво вижда моделът ──")
seen = {}
ai_brief._call_claude = lambda system, user, max_tokens=0: (seen.setdefault("u", user), json.dumps({"tickers": []}))[1]
ai_brief._live_v2_positions = lambda: {}                                                       # v2 tracker-ът е празен (05.10)
cands = [dict(CARDS[t]) for t in ("AMD", "AVT", "ANET", "FTNT")]
with contextlib.redirect_stdout(io.StringIO()):
    ai_brief.ticker_narratives(cands, [], "Defensive")
u = seen["u"]
block = u.split("ВЧЕРАШНИ WATCHLIST TRIGGER-И ЗА ТЕЗИ ТИКЪРИ")[1].split("За тикър от списъка")[0]
trig = json.loads(block[block.index("{"):block.rindex("}") + 1])
assert list(trig) == ["FTNT"] and "Вече в портфейла" not in block and "616.69" not in block and "99.92" not in block and "194.35" not in block
print("  ✓ към модела отива само вчерашният trigger на FTNT; текстовете 'Вече в портфейла от 2026-09-22 (entry $616.69)…' за AMD/AVT/ANET не стигат до него")
config.DATA_DIR = orig_dir
tmp.cleanup()
print()
print("Всички тестове минаха.")
