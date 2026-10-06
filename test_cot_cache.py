"""
Пакет 3 · т.а + т.ж (2026-10-05): кеш на COT тезите в data/cot_theses_cache.json. Ключ: (пазар, as_of, посока на екстремума, версия на
промпта/схемата, модел). Регенерация само при нов as_of, нова посока, нов екстремум или смяна на версията/модела; иначе тезата се ползва
повторно. При провал на batch — старата теза на пазара с флаг stale (най-много 8 дни стара). FORCE_COT_REGEN=1 регенерира всичко.
Ако COT данните са остарели (т.ж) — нищо не се регенерира. Кешът пази суровите механизми (+ изключените с причина); ежедневните проверки
(evaluate_cot_theses) се пускат отгоре всеки ден.

РЕАЛНО: двата последователни седмични набора екстремуми — брифът от 22.09 (17 пазара, as_of 15.09) и от 02.10 (18 пазара, as_of 22.09;
15 общи, 2 само в първия, 3 само във втория, без смяна на посока) от tests/fixtures. СИНТЕТИЧНО: отговорът на модела (tests/fixtures/
cot_model_answers_2026-10-02.json), датите на пусканията, провалените batch-ове, смяната на версията/модела, смяната на посока, повреденият файл.
Кешът е във временна директория — реалният data/cot_theses_cache.json не се пипа.
Пускане: python test_cot_cache.py
"""
import sys, json, pathlib, io, contextlib, re, copy, datetime as dt, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, cot_theses as ct

FIX = ROOT / "tests" / "fixtures"
WK1 = json.loads((FIX / "brief_2026-09-22.json").read_text(encoding="utf-8"))["cot"]
WK2 = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))["cot"]
ANS = json.loads((FIX / "cot_model_answers_2026-10-02.json").read_text(encoding="utf-8"))["markets"]
CHK = json.loads((FIX / "cot_direct_tickers_2026-10-05.json").read_text(encoding="utf-8"))["checked"]
keys = ("market", "category", "net_position", "percentile", "direction", "as_of", "weeks_of_history", "history")
EX1 = [{k: c[k] for k in keys} for c in WK1]
EX2 = [{k: c[k] for k in keys} for c in WK2]
assert (len(EX1), len(EX2)) == (17, 18) and {e["as_of"] for e in EX1} == {"2026-09-15"} and {e["as_of"] for e in EX2} == {"2026-09-22"}

TMP = tempfile.TemporaryDirectory(prefix="mb_cotcache_")
CACHE = pathlib.Path(TMP.name) / "cache.json"
REAL_CACHE = ROOT / "data" / "cot_theses_cache.json"
real_before = REAL_CACHE.read_bytes() if REAL_CACHE.exists() else None

company = {t: r["name"] for t, r in CHK.items() if r["name"]}
for c in WK1 + WK2:
    for k in ("direct_thesis", "cross_sector_thesis"):
        for t in (c.get(k) or {}).get("tickers") or []:
            company.setdefault(t["ticker"], t["company"])
ai_brief._verified_company_name = lambda t: {"name": company.get(t, t), "verified": t in company, "quote_type": (CHK.get(t) or {}).get("quote_type"),
                                              "category": (CHK.get(t) or {}).get("category"), "long_name": company.get(t), "sector": None, "industry": None}
config.COT_BATCH_SIZE = 5
log = {"calls": [], "fail_markets": set(), "answers": ANS}
def fake_claude(system, user, max_tokens=0):
    m = re.search(r"\):\s*(\[.*?\])\n\nВИД НА ПАЗАРА", user, re.S)
    batch = json.loads(m.group(1))
    markets = [b["market"] for b in batch]
    if set(markets) & log["fail_markets"]:
        raise ConnectionError("API недостъпно")
    log["calls"].append(markets)
    return json.dumps({"theses": [{"market": b["market"], "tickers": log["answers"].get(b["market"], [])} for b in batch]}, ensure_ascii=False)
ai_brief._call_claude = fake_claude
D = lambda s: dt.date.fromisoformat(s)


def run(extremes, today, **kw):
    log["calls"].clear()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = ai_brief.cot_theses(extremes, [{"ticker": "AMD"}], [], [], today=D(today), cache_path=CACHE, **kw)
    return {c["market"]: c for c in out}, [m for call in log["calls"] for m in call], buf.getvalue()


def entries():
    return json.loads(CACHE.read_text(encoding="utf-8"))["entries"]


def strip(by):
    """тезите без полетата, които се менят според деня (значки, outside_screener, източник на тезата)"""
    def sub(th):
        th = {k: v for k, v in (th or {}).items() if k not in ("outside_screener", "source", "generated_at")}
        th["tickers"] = [{k: v for k, v in t.items() if k != "markers"} for t in th.get("tickers") or []]
        return th
    return json.dumps({m: {"direct": sub(c["direct_thesis"]), "cross": sub(c["cross_sector_thesis"])} for m, c in by.items()}, sort_keys=True, ensure_ascii=False, default=str)


print("── седмица 1 (РЕАЛНИТЕ 17 екстремума от 22.09): празен кеш → всичко се генерира ──")
r1, gen1, _ = run(EX1, "2026-09-22")
assert sorted(gen1) == sorted(e["market"] for e in EX1) and len(log["calls"]) == 4                       # 17 пазара в batch-ове по 5 → 4 извиквания
assert len(entries()) == 17
ver = ai_brief.cot_prompt_version()
k0 = ct.cache_key("Corn", "2026-09-15", "extreme_long", ver, config.CLAUDE_MODEL)
e0 = entries()[k0]
assert (e0["market"], e0["as_of"], e0["direction"], e0["version"], e0["model"], e0["generated_at"]) == ("Corn", "2026-09-15", "extreme_long", ver, config.CLAUDE_MODEL, "2026-09-22")
assert [t["ticker"] for t in e0["tickers"]] == ["TSN", "PPC"] and e0["excluded"] == []
print(f"  ✓ 17 пазара → 4 AI извиквания (batch ≤5); 17 записа в кеша; ключ = пазар|as_of|посока|версия|модел (версия {ver})")

print()
print("── повторно пускане същия ден и следващите дни: нула AI извиквания ──")
r1b, gen, _ = run(EX1, "2026-09-22")
assert gen == [] and strip(r1b) == strip(r1)
for day in ("2026-09-23", "2026-09-24", "2026-09-26"):
    rb, gen, text = run(EX1, day)
    assert gen == [] and strip(rb) == strip(r1)
assert all(c["cross_sector_thesis"]["source"] == "cache" for c in rb.values())
assert all(c["cross_sector_thesis"]["generated_at"] == "2026-09-22" for c in rb.values())
print("  ✓ 4 последователни дни със същите екстремуми: 0 AI извиквания, тезите са идентични (значките/outside_screener се сменят според деня)")

print()
print("── седмица 2 (РЕАЛНИТЕ 18 екстремума от 02.10, нов as_of 22.09): нов ключ → регенерация ──")
r2, gen2, _ = run(EX2, "2026-09-29")
assert sorted(gen2) == sorted(e["market"] for e in EX2) and len(entries()) == 17 + 18
common = {e["market"] for e in EX1} & {e["market"] for e in EX2}
assert len(common) == 15
print("  ✓ нов as_of → всички 18 пазара са нови ключове и се генерират (15 общи с миналата седмица, 3 нови екстремума, 2 изчезнали);")
print("    старите 17 записа остават в кеша (ползват се като резерва при провал)")
r2b, gen, _ = run(EX2, "2026-09-30")
assert gen == []
print("  ✓ следващия ден: 0 извиквания")

print()
print("── нов екстремум и смяна на посока → само засегнатите се генерират (СИНТЕТИЧНО върху реалните) ──")
EX2b = EX2 + [{**EX2[0], "market": "Platinum", "direction": "extreme_short", "percentile": 4.0}]
r, gen, _ = run(EX2b, "2026-10-01")
assert gen == ["Platinum"] and len(log["calls"]) == 1
flipped = [dict(e, direction="extreme_short") if e["market"] == "Wheat" else e for e in EX2b]
r, gen, _ = run(flipped, "2026-10-01")
assert gen == ["Wheat"]
w = r["Wheat"]["cross_sector_thesis"]
assert w["source"] == "generated" and r["Corn"]["cross_sector_thesis"]["source"] == "cache"
print("  ✓ нов екстремум (Platinum) → 1 извикване само за него; Wheat сменя посока (extreme_long → extreme_short) → само Wheat се регенерира")
r, gen, _ = run(flipped, "2026-10-01")
assert gen == []
print("  ✓ ефектите при сменената посока се преизчисляват от кода, кешираните механизми стоят")

print()
print("── версия, модел, FORCE_COT_REGEN ──")
v_before = ai_brief.cot_prompt_version()
orig_sys = ai_brief.SYSTEM_COT
ai_brief.SYSTEM_COT = orig_sys + " Промяна."
v_sys = ai_brief.cot_prompt_version()
r, gen, _ = run(EX2, "2026-10-02")
assert v_sys != v_before and len(gen) == 18                                                                    # нов текст → нова версия → всичко се регенерира
ai_brief.SYSTEM_COT = orig_sys
orig_txt = config.COT_MECHANISM_SIGN["input_cost"]["text"]
config.COT_MECHANISM_SIGN["input_cost"]["text"] = orig_txt + "."
assert ai_brief.cot_prompt_version() not in (v_before, v_sys)                                                  # таблицата за механизми е част от версията
config.COT_MECHANISM_SIGN["input_cost"]["text"] = orig_txt
orig_direct = config.COT_DIRECT_TICKERS["Gold"]["tickers"]
config.COT_DIRECT_TICKERS["Gold"]["tickers"] = orig_direct[:1]
assert ai_brief.cot_prompt_version() == v_before                                                                # таблицата с директни тикъри НЕ е част от версията
config.COT_DIRECT_TICKERS["Gold"]["tickers"] = orig_direct
r, gen, _ = run(EX2, "2026-10-02")
assert gen == []                                                                                                # със същата версия и модел — от кеша
orig_model = config.CLAUDE_MODEL
config.CLAUDE_MODEL = "claude-друг-модел"
r, gen, _ = run(EX2, "2026-10-02")
assert len(gen) == 18
config.CLAUDE_MODEL = orig_model
config.FORCE_COT_REGEN = True
r, gen, text = run(EX2, "2026-10-03")
assert len(gen) == 18 and "FORCE_COT_REGEN" in text
config.FORCE_COT_REGEN = False
r, gen, _ = run(EX2, "2026-10-03")
assert gen == []
print("  ✓ нов системен текст → нова версия → 18 регенерации; промяна в таблицата за механизми също сменя версията, а в таблицата с директни тикъри — не;")
print("    друг модел → 18 регенерации; FORCE_COT_REGEN=1 → 18 регенерации въпреки кеша; после пак от кеша")

print()
print("── провал на batch: старата теза с флаг stale (най-много 8 дни стара) ──")
CACHE.unlink()
run(EX1, "2026-09-22")                                                                                          # седмица 1 в кеша (генерирана 22.09)
log["fail_markets"] = {"Corn"}                                                                                  # batch-ът с Corn пада
r, gen, text = run(EX2, "2026-09-27")                                                                           # 5 дни след 22.09 (≤ 8)
cn = r["Corn"]["cross_sector_thesis"]
assert cn["stale"] is True and cn["source"] == "stale_fallback" and cn["generated_at"] == "2026-09-22"
assert cn["stale_note"].startswith("Остаряла теза: генерирана на 2026-09-22 за отчет към 2026-09-15 (extreme_long); новата не е налична — моделът не върна пазара, следващият run опитва пак.")
assert [t["ticker"] for t in cn["tickers"]] == ["TSN", "PPC"]                                                    # старата теза се показва
assert ai_brief.COT_DIAG["cache"]["stale_fallback"] >= 1
failed = [m for m, c in r.items() if c["cross_sector_thesis"].get("stale")]
sources = {m: c["cross_sector_thesis"]["source"] for m, c in r.items()}
assert "Corn" in failed and set(sources.values()) <= {"stale_fallback", "generated", "none"}
new_in_failed_batch = [m for m, src in sources.items() if src == "none"]                                         # нов пазар (без предишна теза) от провалилия се batch → празна
assert all(m not in {e["market"] for e in EX1} for m in new_in_failed_batch)
print(f"  ✓ batch-ът с Corn пада: {len(failed)} пазара от него със СТАРАТА теза (генерирана 22.09, 5 дни) и бележка 'Остаряла теза…'; "
      f"{len(new_in_failed_batch)} нови пазара без предишна теза — празна cross; останалите са нови")
# по-стара от 8 дни → празна теза с причина
log["fail_markets"] = {m for m in log["fail_markets"]} | {e["market"] for e in EX2}
r, gen, _ = run(EX2, "2026-10-02")                                                                              # 10 дни след 22.09 (> 8)
assert all(c["cross_sector_thesis"]["source"] in ("none", "cache") for c in r.values())
assert r["Corn"]["cross_sector_thesis"]["empty_reason"] == "моделът не върна пазара, следващият run опитва пак" and not r["Corn"]["cross_sector_thesis"]["tickers"]
assert [t["ticker"] for t in r["Corn"]["direct_thesis"]["tickers"]] == ["CORN"]                                  # директната е от таблицата и остава
log["fail_markets"] = set()
print("  ✓ резервата е по-стара от 8 дни (10) → без стара теза: cross е празна с причина, директната (от таблицата) остава")

print()
print("── ж: остарели COT данни → нищо не се регенерира ──")
CACHE.unlink()
run(EX1, "2026-09-22")
r, gen, text = run(EX2, "2026-09-29", data_stale=True)                                                          # ключовете на седмица 2 липсват, данните са "стари"
assert gen == [] and "данните са остарели — без регенерация" in text
assert all(c["cross_sector_thesis"]["source"] == "stale_fallback" and "COT данните са остарели — тезите не се регенерират" in c["cross_sector_thesis"]["stale_note"] for m, c in r.items() if m in {e["market"] for e in EX1})
new_only = [m for m in r if m not in {e["market"] for e in EX1}]
assert new_only and all(r[m]["cross_sector_thesis"]["empty_reason"] == "COT данните са остарели — тезите не се регенерират" for m in new_only)
assert [t["ticker"] for t in r["Copper"]["direct_thesis"]["tickers"]] == ["CPER", "FCX", "SCCO"]                  # директната е от таблицата
r, gen, _ = run(EX1, "2026-09-29", data_stale=True)                                                             # ключовете съществуват → от кеша, дори при stale
assert gen == [] and all(c["cross_sector_thesis"]["source"] == "cache" for c in r.values())
r, gen, _ = run(EX2, "2026-10-12", data_stale=True)                                                             # 20 дни след генерирането → без резерва
assert gen == [] and all(c["cross_sector_thesis"]["source"] == "none" for c in r.values())
print("  ✓ данни остарели: нула AI извиквания; липсващ ключ → старата теза (≤8 дни) с бележка 'COT данните са остарели — тезите не се регенерират', нов пазар → празна с тази причина;")
print("    наличен ключ → от кеша; резерва по-стара от 8 дни → без стара теза; директната теза (таблица) се показва винаги")

print()
print("── какво пази кешът ──")
CACHE.unlink()
log["answers"] = dict(ANS, Corn=ANS["Corn"] + [{"ticker": "ADM", "company": "ADM", "mechanisms": [{"type": "input_cost", "quote": "купува зърно"}, {"type": "output_price", "quote": "продава продукти"}]}],
                      Wheat=[])
r, gen, _ = run(EX2, "2026-10-02")
ent = {v["market"]: v for v in entries().values()}
assert [x["ticker"] for x in ent["Corn"]["tickers"]] == ["TSN", "PPC", "ADM"]                                     # суровият отговор, цял
assert ent["Corn"]["excluded"] == [{"ticker": "ADM", "code": "mixed", "reason": "mixed: противоположен ефект — цена на продукта (+) срещу разход за суровина (−)"}]
assert ent["Wheat"]["tickers"] == [] and ent["Wheat"]["excluded"] == []
r, gen, _ = run(EX2, "2026-10-03")
assert gen == [] and r["Wheat"]["cross_sector_thesis"]["tickers"] == [] and r["Wheat"]["cross_sector_thesis"]["empty_reason"] == "моделът не предложи тикър със структурен механизъм към този инструмент"
print("  ✓ кешът пази СУРОВИЯ отговор и изключените с причина (ADM — mixed); празен отговор на модела (Wheat) също се кешира и не се пита наново; empty_reason е от кода")

print()
print("── устойчивост на файла ──")
CACHE.write_text("{ не е json")
r, gen, text = run(EX2, "2026-10-04")
assert len(gen) == 18 and "кешът на тезите е повреден" in text and len(entries()) == 18
CACHE.write_text(json.dumps({"entries": "боклук"}))
r, gen, _ = run(EX2, "2026-10-04")
assert len(gen) == 18
CACHE.unlink()
r, gen, _ = run(EX2, "2026-10-04")
assert len(gen) == 18 and not list(pathlib.Path(TMP.name).glob(".cot_theses_*"))                                  # няма останали временни файлове
print("  ✓ повреден JSON / неочаквана форма / липсващ файл → празен кеш и регенерация (без изключение); записът е атомичен (няма временни файлове)")
cache = ct.load_cache(CACHE)
old = {**cache["entries"][next(iter(cache["entries"]))]}
cache["entries"]["стар"] = {**old, "generated_at": "2026-08-01", "as_of": "2026-07-28", "market": old["market"]}          # > 30 дни, но не е най-новият за пазара
cache["entries"]["единствен"] = {**old, "market": "Измислен пазар", "generated_at": "2026-08-01"}                         # > 30 дни, но е единственият за пазара
n_before = len(cache["entries"])
pruned = ct.prune_cache(cache, D("2026-10-04"))
assert pruned == 1 and "стар" not in cache["entries"] and "единствен" in cache["entries"] and len(cache["entries"]) == n_before - 1
print("  ✓ записи по-стари от 30 дни се чистят, освен най-новия за всеки пазар (1 махнат, единственият за 'Измислен пазар' остава)")

after = REAL_CACHE.read_bytes() if REAL_CACHE.exists() else None
assert after == real_before
print("  ✓ реалният data/cot_theses_cache.json не е пипнат")
print()
print("Всички тестове минаха.")
