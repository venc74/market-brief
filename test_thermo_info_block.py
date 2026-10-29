"""
29.10.2026 · разходката, т. 2 (термометърът), решение 1: трите информативни уреда (Fed Net Liquidity, SOFR − IORB, основна инфлация) са видими, но отделени — под уредите, които
решават (8-те броени + Distribution Days, който блокира Offensive), в блок със заглавие „Информативни — не влизат в режима“, по-малки и по-бледи; не са сгънати.
Редът в секцията: уредите, които решават → „Запас до смяна на режима“ → информативните → „Скрити днес“. Скрит информативен уред не е в блока — той е в „Скрити днес“, както досега.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json — брифът от 19.10 (10 уреда, от тях 2 информативни; основната инфлация за август).
СИНТЕТИЧНО (означено): скритата Fed Net Liquidity в т. 3, брифът без информативни уреди в т. 4.
Пускане: python test_thermo_info_block.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_tinfo_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import render

B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
txt = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))


def section(b):
    with contextlib.redirect_stdout(io.StringIO()):
        h = render.render_dashboard(b, publish=False)
    s = h[h.index("<h2>Пазарен термометър</h2>"):]
    return h, s[:s.index("</section>")]


def names(fragment):
    return re.findall(r'<div class="t-name">(.*?)(?:\s*<span|</div>)', fragment)


print("── 1. РЕАЛНИЯТ бриф от 19.10: горе — уредите, които решават; долу — информативните ──")
page, sec = section(copy.deepcopy(B19))
top, rest = sec.split('<div class="thermo-info">', 1)
counted = [i["name"] for i in B19["thermometer"]["indicators"] if not i.get("informational") and not i.get("hide")]
assert len(counted) == 8 and names(top) == counted + ["Distribution Days"], names(top)
assert names(rest) == ["Fed Net Liquidity", "SOFR − IORB (финансиране)", "Основна инфлация"], names(rest)
assert rest.lstrip().startswith('<div class="thermo-info-head">Информативни — не влизат в режима</div>')
assert rest.count('class="t-card ') == 3 and all(" info" in c for c in re.findall(r'class="t-card[^"]*"', rest))     # и трите — с рамката на информативните
assert "<details" not in sec                                                                                       # не са сгънати
t = txt(sec)
assert t.index("Distribution Days") < t.index("Запас до смяна на режима") < t.index("Информативни — не влизат в режима") < t.index("Fed Net Liquidity")
print(f"  ✓ горе {len(names(top))}: 8 броени + Distribution Days; „Запас до смяна на режима“; после „Информативни — не влизат в режима“: {', '.join(names(rest))}")

print()
print("── 2. по-малки и по-бледи (CSS) ──")
css = page[:page.index("</style>")]
op = float(re.search(r"\.thermo-info \{[^}]*opacity: ([.\d]+)", css).group(1))
val = float(re.search(r"\.thermo-info \.t-val \{[^}]*font-size: ([\d.]+)px", css).group(1))
base = float(re.search(r"\n\s*\.t-val \{[^}]*font-size: ([\d.]+)px", css).group(1))                       # общото правило (не това на блока)
assert op < 1 and val < base
print(f"  ✓ opacity {op}, стойност {val:g}px срещу {base:g}px горе")

print()
print("── 3. СИНТЕТИЧНО: скрита Fed Net Liquidity — не е в блока, а в „Скрити днес“ ──")
b = copy.deepcopy(B19)
nl = next(i for i in b["thermometer"]["indicators"] if i["name"] == "Fed Net Liquidity")
nl.update(value=None, hide=True, label="", hide_reason="RRPONTSYD застояла")
_, sec3 = section(b)
top3, rest3 = sec3.split('<div class="thermo-info">', 1)
assert "Fed Net Liquidity" not in names(top3) + names(rest3) and names(rest3) == ["SOFR − IORB (финансиране)", "Основна инфлация"]
assert "Скрити днес: Fed Net Liquidity — RRPONTSYD застояла (информативен, не влиза в режима)" in txt(sec3)
print("  ✓ блокът — SOFR и основната инфлация; „Скрити днес: Fed Net Liquidity — … (информативен, не влиза в режима)“")

print()
print("── 4. СИНТЕТИЧНО: без информативни уреди и без основна инфлация — няма заглавие ──")
b = copy.deepcopy(B19)
b["thermometer"]["indicators"] = [i for i in b["thermometer"]["indicators"] if not i.get("informational")]
b["macro"]["core_inflation"] = None
_, sec4 = section(b)
assert "thermo-info" not in sec4 and "Информативни" not in sec4 and len(names(sec4)) == 9
print("  ✓ само 8-те + Distribution Days, без празен блок")
print("\n✅ test_thermo_info_block: всичко мина")
