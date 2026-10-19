"""
19.10.2026 · етап 2, т. 17в: Form 4 — ролята на инсайдъра по officerTitle. Подниз "ceo/cfo/president/coo" пропускаше ИЗПИСАНИТЕ титли ("Chief Financial Officer" няма "cfo") и броеше всеки
"Vice President" (заради "president") и "Special Advisor to CEO". insider_buying.is_key_role: съкращенията, изписаните Chief Executive/Financial/Operating Officer и Principal
Executive/Financial Officer, президент — но не вицепрезидент.

РЕАЛНО: tests/fixtures/form4_officer_titles_2026-10-19.json — 153 officerTitle (isOfficer = 1) от реални Form 4 (01.09–16.10.2026, извадка по пълнотекстово търсене — не честота);
tests/fixtures/form4/*.xml — трите реални Form 4 от пакета за Form 4 (C6). СИНТЕТИЧНО: няма.
Пускане: python test_form4_key_role.py
"""
import sys, json, pathlib, collections
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
from src import insider_buying as ib

T = json.loads((ROOT / "tests" / "fixtures" / "form4_officer_titles_2026-10-19.json").read_text(encoding="utf-8"))["titles"]
assert len(T) == 153
old = lambda t: any(k in t.lower() for k in ib._OFFICER_TITLE_KEYWORDS)
missed = collections.Counter(t for t, _ in T if not old(t) and ib.is_key_role(t))
false_ = collections.Counter(t for t, _ in T if old(t) and not ib.is_key_role(t))
assert sum(missed.values()) == 72 and missed["Chief Financial Officer"] == 22 and missed["Chief Operating Officer"] == 20 and missed["Chief Executive Officer"] == 10
assert sum(false_.values()) == 20 and false_["Executive Vice President"] == 6 and false_["Special Advisor to CEO"] == 1
KEY = {"Chief Executive Officer", "CHIEF FINANCIAL OFFICER", "Chief  Financial Officer", "EVP, Chief Operating Officer", "Vice President - CFO", "CFO & Executive Vice President",
       "President & CEO", "Interim President and CEO", "Pres & Chief Operating Officer", "CEO/CIO", "President", "CEO, President, BOD Chair", "Executive Vice President, CFO"}
NOT = {"Executive Vice President", "Senior Vice President", "VICE PRESIDENT", "Sr. Vice President", "Vice President of Exploration", "Special Advisor to CEO", "Executive Chairman", "SEE REMARKS"}
titles = {t for t, _ in T}
assert KEY <= titles and NOT <= titles
assert all(ib.is_key_role(t) for t in KEY) and not any(ib.is_key_role(t) for t in NOT)
FX = sorted((ROOT / "tests" / "fixtures" / "form4").glob("*.xml"))
own = [o for f in FX for o in (ib._parse_form4(f.read_text(encoding="utf-8")) or {}).get("owners", [])]
role = {o["title"]: ib.is_key_role(o["title"]) for o in own if o["title"]}
assert role == {"President & CEO": True}                                                          # TFC 0001534574-26-000016 (покупка с код P); другите два нямат P — парсерът ги прескача
raw = "".join(f.read_text(encoding="utf-8") for f in FX)
assert "<officerTitle>Chief Consumer &amp; SB BK Officer</officerTitle>" in raw and not ib.is_key_role("Chief Consumer & SB BK Officer")
print(f"  ✓ 153 реални титли: +{sum(missed.values())} пропуснати ключови (Chief Financial ×22, Chief Operating ×20, Chief Executive ×10, …), −{sum(false_.values())} фалшиви (Executive Vice President ×6, …, Special Advisor to CEO)")
print("  ✓ реалните Form 4 от fixtures: 'President & CEO' — ключова, 'Chief Consumer & SB BK Officer' — не")
print("\n✅ test_form4_key_role: всичко мина")
