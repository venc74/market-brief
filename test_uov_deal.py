"""
28.10.2026 · UOV✓ не се показва при тикър със сделка — опционният обем следва условията на сделката, не сетъпа. Реално: ROKU на 28.10 — запис в buy-stop книгата с етикет "deal"
(Fox Corporation) и маркер „UOV✓ (calls)“: ≈ 0.67× OI, calls 92% — върху цена, привързана към офертата. В историята: 1 такъв случай (28.10).
  • редовете в книгите (main.attach_position_uov): запис с deal → без маркер, uov_hidden с причината;
  • картите (spinoff_watch.annotate_mergers → drop_uov): с маркера „цел на придобиване“ UOV✓ се маха.

РЕАЛНО: tests/fixtures/uov_deal_2026-10-28.json — редовете на buy-stop книгата от брифа на 28.10 (ROKU с deal и UOV✓, два реда без сделка); tests/fixtures/deal_roku_2026-10-23.json —
картата на ROKU от 23.10. СИНТЕТИЧНО (означено): подмененото unusual_options.candidate_markers (връща реалния текст на маркера), маркерът върху картата от 23.10.
Пускане: python test_uov_deal.py
"""
import sys, json, copy, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_uovdeal_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import main, unusual_options, spinoff_watch as sw

FX = json.loads((ROOT / "tests" / "fixtures" / "uov_deal_2026-10-28.json").read_text(encoding="utf-8"))
REAL_TITLE = FX["roku_row"]["markers"][0]["title"]
assert FX["roku_row"]["deal"]["buyer"] == "Fox Corporation" and FX["roku_row"]["markers"][0]["tag"] == "UOV✓ (calls)" and "calls 92%" in REAL_TITLE

print("── 1. редовете в книгите ──")
rows = [{k: v for k, v in FX["roku_row"].items() if k != "markers"}] + [{k: v for k, v in r.items() if k != "markers"} for r in FX["other_rows"]]
tick = [r["ticker"] for r in rows]
real_cm = unusual_options.candidate_markers
unusual_options.candidate_markers = lambda ts: ({t: {"note": REAL_TITLE, "direction": "calls"} for t in ts}, {"requested": len(ts), "with_ratio": len(ts), "marked": len(ts)})   # СИНТЕТИЧНО
try:
    main.attach_position_uov(rows)
finally:
    unusual_options.candidate_markers = real_cm
r0 = rows[0]
assert r0["ticker"] == "ROKU" and not r0.get("markers") and r0["uov_hidden"] == "сделка — опционният обем следва условията на сделката"
assert all(any(str(m["tag"]).startswith("UOV✓") for m in r.get("markers") or []) for r in rows[1:])
print(f"  ✓ ROKU (deal) — без UOV✓; {', '.join(tick[1:])} (без сделка) — с маркера")

print()
print("── 2. картите ──")
card = copy.deepcopy(json.loads((ROOT / "tests" / "fixtures" / "deal_roku_2026-10-23.json").read_text(encoding="utf-8"))["card_2026_10_23"])
card.pop("merger_target", None)
card["markers"] = (card.get("markers") or []) + [{"tag": "UOV✓ (calls)", "title": REAL_TITLE}]                    # СИНТЕТИЧНО: маркерът върху картата от 23.10
other = [m["tag"] for m in card["markers"] if not m["tag"].startswith("UOV")]
assert sw.annotate_mergers([[card]], {"ROKU": {"buyer": "Fox Corporation", "announced": "2026-06-14", "filing_date": "2026-06-15"}}) == 1
assert not any(m["tag"].startswith("UOV") for m in card["markers"]) and [m["tag"] for m in card["markers"]] == other and card["uov_hidden"].startswith("сделка")
plain = {"ticker": "AAPL", "markers": [{"tag": "UOV✓ (puts)", "title": "…"}]}
assert sw.annotate_mergers([[plain]], {"ROKU": {"buyer": "Fox Corporation"}}) == 0 and plain["markers"][0]["tag"] == "UOV✓ (puts)"
print("  ✓ с маркера „цел на придобиване“ UOV✓ се маха (другите маркери остават); тикър без сделка — непокътнат")
print("\n✅ test_uov_deal: всичко мина")
