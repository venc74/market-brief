"""
16.11.2026 (пакет 16.11, т. 13): KDP обяви емисия на акции за $2 млрд (12.11, −7%), а брифът мълчеше. Проверката (src/offering_watch.py) — 424B1/B3/B4/B5/B7 в последните
OFFERING_LOOKBACK_DAYS дни с обложка за акции → „⚠ емисия на акции“; дълг → нищо; S-1 / S-3 / F-1 / F-3 → по-лек ред „регистрация“; 424B2 и S-3ASR — пропуснати. За картите,
книгите и наблюдаваните; списъците от EDGAR — общите с проверката за отделяне.

РЕАЛНО: tests/fixtures/edgar_kdp_offering_2026-11-16.json — data.sec.gov/submissions за KDP (подаванията от 01.10.2026) и началото на двата 424B5 (12.11 — предварителен,
„$2,000,000,000 Common Stock“; 16.11 — „57,971,015 Shares Common Stock“ по $34.50), изтеглено 16.11.2026 през браузъра. brief_2026-10-19.json — рамката.
СИНТЕТИЧНО (означено): т. 3 — обложка за дълг и S-3; CIK картата; подмененото теглене.
Пускане: python test_offering_watch.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_offer_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import offering_watch as ow, render

FX = json.loads((ROOT / "tests" / "fixtures" / "edgar_kdp_offering_2026-11-16.json").read_text(encoding="utf-8"))
SUB = {"cik": FX["cik"], "name": FX["name"], "filings": FX["filings"]}
DOCS = {acc: d["head"] for acc, d in FX["docs"].items()}
q = lambda: contextlib.redirect_stdout(io.StringIO())


def get(url):
    if "submissions" in url:
        return json.dumps(SUB)
    acc = next(a for a in DOCS if a.replace("-", "") in url)
    return DOCS[acc]


print("── 1. РЕАЛНО: подаванията на KDP и обложките ──")
fs = ow.recent_filings(SUB, "2026-11-06", "2026-11-16")
assert [(f["form"], f["date"]) for f in fs] == [("424B5", "2026-11-16"), ("424B5", "2026-11-12")], fs
c12 = ow.classify(ow.cover_text(DOCS["0001193125-26-457001"]))
c16 = ow.classify(ow.cover_text(DOCS["0001193125-26-461405"]))
assert c12 == {"kind": "акции", "title": "$2,000,000,000 Common Stock", "preliminary": True}, c12
assert c16 == {"kind": "акции", "title": "57,971,015 Shares Common Stock", "preliminary": False}, c16
print(f"  ✓ 12.11 — „{c12['title']}“ (предварителен); 16.11 — „{c16['title']}“")

print("── 2. РЕАЛНО: проверката за 16.11 ──")
with q():
    found = ow.check(["KDP", "XXXX"], dt.date(2026, 11, 16), get=get, cik_map={"KDP": 1418135}, subs={})
T = found["KDP"]["text"]
assert T == "⚠ емисия на акции — 424B5 от 16.11: „57,971,015 Shares Common Stock“ · и 424B5 от 12.11 (предварителен)", T
assert ow.LAST_DIAG["checked"] == 1 and ow.LAST_DIAG["unchecked"] == ["XXXX"] and ow.LAST_DIAG["fetched"] == 2
with q():
    again = ow.check(["KDP"], dt.date(2026, 11, 16), get=get, cik_map={"KDP": 1418135}, subs={})
assert again["KDP"]["text"] == T and ow.LAST_DIAG["fetched"] == 0                                   # кешът по документ
with q():
    late = ow.check(["KDP"], dt.date(2026, 11, 27), get=get, cik_map={"KDP": 1418135}, subs={})
assert late == {}                                                                                   # извън прозореца (10 дни)
print(f"  ✓ {T}; повторно — от кеша; на 27.11 — извън прозореца")

print("── 3. СИНТЕТИЧНО: дълг, регистрация, 424B2 ──")
assert ow.classify("Prospectus Supplement $1,000,000,000 4.500% Senior Notes due 2031")["kind"] == "дълг"
assert ow.line([{"form": "S-3", "date": "2026-11-13", "kind": "регистрация"}]) == "регистрация на ценни книжа — S-3 от 13.11 (може да последва емисия)"
assert ow.line([{"form": "424B5", "date": "2026-11-13", "kind": "неясно"}]).startswith("⚠ проспект за ценни книжа — 424B5 от 13.11")
sub2 = copy.deepcopy(SUB); r = sub2["filings"]["recent"]
r["form"][0] = "424B2"; r["form"][3] = "S-3ASR"
assert ow.recent_filings(sub2, "2026-11-06", "2026-11-16") == []
print("  ✓ дълг — без ред; S-3 — „регистрация“; 424B2 и S-3ASR — пропуснати")

print("── 4. картата, наблюдаваният, книгата ──")
cards = [{"ticker": "KDP"}, {"ticker": "NDAQ"}]
assert ow.annotate([cards], found) == 1 and cards[0]["offering_warning"] == T
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
b = copy.deepcopy(B19); b["offering_warnings"] = {"KDP": T}
assert render.offering_lines(b) == [f"KDP — {T}"]
with q():
    page = render.render_dashboard(b, publish=False)
assert f"KDP — {T}" in page and "(EDGAR: 424B / S-1 / S-3 за последните 10 дни — книгите и наблюдаваните)" in page
src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
assert 'offering_watch.check(card_t + live_t + watch_t, today, subs=edgar_subs)' in src and '"offering_warnings":' in src
print("  ✓ картата носи реда; книгите / наблюдаваните — редът в CANSLIM")
print("\n✅ test_offering_watch: всичко мина")
