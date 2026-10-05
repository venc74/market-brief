"""
Пакет 4б (06.10.2026) · т.в: списъкът "Insider Buying" отпада (и скенерът на целия S&P500+NDX100 в main); остава маркер INS✓ върху НАШИ кандидати и позиции с кой, кога, колко при hover/клик.
Теглене на Form 4 само за нашите тикъри (insider_buying.insider_for); етикетите за давност от 4а остават в маркера (последна транзакция, остарели данни); провалът на тегленето излиза като банер,
не като тих липсващ маркер.

РЕАЛНО: редовете от брифа на 02.10.2026 (tests/fixtures/brief_2026-10-02.json, старият списък): COO (cluster, $1.88M), TFC (President & CEO Lyons, $1.02M, 17.09), TSN — маркерите се строят от
тях; страницата на същия бриф вече няма секцията. СИНТЕТИЧНО: суровите Form 4 транзакции (AAA…), подмененото теглене от SEC, кешът във временна директория, дати/суми в граничните случаи.
Пускане: python test_insider_markers.py
"""
import sys, json, pathlib, tempfile, copy, ast, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import insider_buying as ib, data_warnings, enrich, render
from src import main as brief_main

D = dt.date.fromisoformat
FIX = ROOT / "tests" / "fixtures"
B02 = json.loads((FIX / "brief_2026-10-02.json").read_text(encoding="utf-8"))
B05 = json.loads((FIX / "brief_2026-10-05.json").read_text(encoding="utf-8"))
REAL = {r["ticker"]: r for r in B02["insider_buying"]}
assert {"COO", "TFC", "TSN"} <= set(REAL) and REAL["COO"]["cluster"] is True

tmp = tempfile.TemporaryDirectory(prefix="mb_ins_")
config.DATA_DIR = pathlib.Path(tmp.name)
config.DOCS_DIR = pathlib.Path(tmp.name) / "docs"
config.DOCS_DIR.mkdir()

print("── маркерът от РЕАЛНИ редове (02.10) ──")
m = ib.insider_marker(REAL["TFC"], D("2026-10-05"))
assert m["tag"] == "INS✓"
assert m["title"].splitlines() == ["Insider buying (Form 4, покупка на open market): общо $1.0M от 1 инсайдър.",
                                   "• Lyons Michael P. (President & CEO) — 2026-09-17 — $1.0M", "Последна транзакция: 2026-09-17 (преди 18 дни)."], m["title"]
m = ib.insider_marker(REAL["COO"], D("2026-10-05"))
assert m["tag"] == "INS✓ CLUSTER" and "общо $1.9M от " in m["title"] and "CLUSTER: 3+ различни инсайдъри за 14 дни." in m["title"]
assert "• Kurzius Lawrence Erik — 2026-09-16 — $549k" in m["title"] and "Последна транзакция: 2026-09-16 (преди 19 дни)." in m["title"]
print("  ✓ TFC: 'общо $1.0M от 1 инсайдър' · 'Lyons Michael P. (President & CEO) — 2026-09-17 — $1.0M' · 'Последна транзакция: 2026-09-17 (преди 18 дни)'")
print("  ✓ COO: INS✓ CLUSTER, $1.9M, имената/датите/сумите по инсайдър, 'CLUSTER: 3+ различни инсайдъри за 14 дни'")
print("    текст на маркера за TFC:", ib.insider_marker(REAL["TFC"], D("2026-10-05"))["title"].replace("\n", " | "))

print()
print("── insider_for (СИНТЕТИЧНИ Form 4, подмененото SEC теглене) ──")
T = lambda tk, name, title, off, date, val, **kw: {"ticker": tk, "company": tk + " Inc", "insider_name": name, "title": title, "is_officer_role": off,
                                                    "transaction_date": D(date), "shares": 100, "price": val / 100, "value": val, "internal_transfer": False, **kw}
RAW = [T("AAA", "Smith J", "CEO", True, "2026-09-30", 250_000), T("AAA", "Doe A", "CFO", True, "2026-10-01", 120_000),
       T("BBB", "Dir One", "", False, "2026-09-29", 300_000),                                                           # директор без cluster — не е сигнал
       T("CCC", "D1", "", False, "2026-09-25", 150_000), T("CCC", "D2", "", False, "2026-09-26", 150_000), T("CCC", "D3", "", False, "2026-09-27", 150_000),   # 3 директори → cluster
       T("DDD", "Small", "CEO", True, "2026-09-30", 50_000),                                                             # под $100k
       T("ZZZ", "Not", "CEO", True, "2026-09-30", 900_000)]                                                              # не е поискан тикър
DIAG = {"ciks_resolved": 4, "tickers_with_filings": 4, "submissions_fetch_errors": 0, "unique_filings_processed": 8}
ib._fetch_raw_transactions = lambda universe, since: (RAW, dict(DIAG))
g, st = ib.insider_for(["AAA", "BBB", "CCC", "DDD"], D("2026-10-05"))
assert sorted(g) == ["AAA", "CCC"] and g["AAA"]["total_value"] == 370_000 and g["AAA"]["cluster"] is False and g["CCC"]["cluster"] is True
assert st["kind"] == "ok" and st["found"] == 2 and not st["stale"] and st["note"] == "проверени 4 от 4 тикъра"
print("  ✓ AAA (CEO+CFO, $370k) и CCC (3 директори = cluster) → маркери; BBB (директор без cluster), DDD (< $100k) и непоисканият ZZZ — не; статус ok")
assert ib.insider_marker(g["CCC"], D("2026-10-05"))["tag"] == "INS✓ CLUSTER" and ib.insider_marker(g["AAA"], D("2026-10-05"))["tag"] == "INS✓"

# легитимна нула / частичен / провал
ib._fetch_raw_transactions = lambda universe, since: ([], dict(DIAG))
g0, st0 = ib.insider_for(["QQQ"], D("2026-10-06"))
assert g0 == {} and st0["kind"] == "legit_zero" and "нито една квалифицираща покупка" in st0["note"]
ib._fetch_raw_transactions = lambda universe, since: (RAW[:2], {**DIAG, "submissions_fetch_errors": 1})
gp, stp = ib.insider_for(["AAA"], D("2026-10-06"))
assert stp["kind"] == "ok_partial" and "1 от 4 заявки към SEC не успяха" in stp["note"] and "AAA" in gp
ib._fetch_raw_transactions = lambda universe, since: ([], {**DIAG, "submissions_fetch_errors": 2})
_, stf = ib.insider_for(["QQQ"], D("2026-10-06"))
assert stf["kind"] == "failed" and "липсата на покупки не е сигурна" in stf["note"]
ib._fetch_raw_transactions = lambda universe, since: ([], {**DIAG, "ciks_resolved": 0})
assert ib.insider_for(["QQQ"], D("2026-10-06"))[1]["kind"] == "failed"
print("  ✓ легитимна нула (чисто теглене без покупки) ≠ провал: частичен (ok_partial), 2 грешки без резултат (failed), без CIK мапинг (failed)")

print()
print("── давност: при провал — последните известни редове, ясно маркирани ──")
ib._fetch_raw_transactions = lambda universe, since: (RAW, dict(DIAG))
ib._marker_cache_path().unlink(missing_ok=True)
ib.insider_for(["AAA", "CCC"], D("2026-10-05"))                                        # успешно теглене на 05.10 → кеш
ok_cache = json.loads(ib._marker_cache_path().read_text(encoding="utf-8"))
assert sorted(ok_cache["rows"]) == ["AAA", "CCC"] and ok_cache["fetched"] == {"AAA": "2026-10-05", "CCC": "2026-10-05"}


def boom(universe, since):
    raise RuntimeError("SEC недостъпен")


ib._fetch_raw_transactions = boom
gs, sts = ib.insider_for(["AAA", "XYZ"], D("2026-10-07"))
assert sts["kind"] == "failed" and sts["stale"] and sts["data_date"] == "2026-10-05" and sorted(gs) == ["AAA"]
assert gs["AAA"]["stale"] and gs["AAA"]["data_date"] == "2026-10-05" and gs["AAA"]["latest_txn_date"] == "2026-10-01"
mt = ib.insider_marker(gs["AAA"], D("2026-10-07"))["title"]
assert "⚠ остарели данни — днешното теглене не успя; показаното е от тегленето на 2026-10-05." in mt and "Последна транзакция: 2026-10-01 (преди 6 дни)." in mt
print("  ✓ SEC недостъпен на 07.10: AAA се показва от тегленето на 05.10 с 'остарели данни' и 'последна транзакция 2026-10-01 (преди 6 дни)'; тикър без кеш (XYZ) — няма маркер")
# кешът пази стария ред, ако тикърът не е поискан; стар запис (>30 дни) се чисти
ib._fetch_raw_transactions = lambda universe, since: ([], dict(DIAG))
ib.insider_for(["QQQ"], D("2026-10-07"))
c2 = json.loads(ib._marker_cache_path().read_text(encoding="utf-8"))
assert sorted(c2["rows"]) == ["AAA", "CCC"]
ib.insider_for(["QQQ"], D("2026-11-20"))
assert json.loads(ib._marker_cache_path().read_text(encoding="utf-8"))["rows"] == {}
print("  ✓ кешът пази редовете на тикъри, които днес не са поискани; записи над ~30 дни се чистят")

print()
print("── банерът при провал (data_warnings) ──")
w = data_warnings.collect(None, None, insider_status={"kind": "failed", "note": "тегленето гръмна: X", "stale": False}, uov_diag=None)
assert [x["source"] for x in w] == ["insider"] and "маркерите INS✓ липсват днес; това НЕ значи, че няма insider покупки" in w[0]["message"]
w = data_warnings.collect(None, None, insider_status={"kind": "failed", "note": "n", "stale": True, "data_date": "2026-10-05"})
assert "са от тегленето на 2026-10-05" in w[0]["message"]
assert data_warnings.collect(None, None, insider_status={"kind": "legit_zero"}) == [] and data_warnings.collect(None, None, insider_status={"kind": "ok"}) == []
assert "непълни" in data_warnings.collect(None, None, insider_status={"kind": "ok_partial", "note": "1 от 4 заявки към SEC не успяха — маркерите може да са непълни"})[0]["message"]
u = data_warnings.collect(None, None, uov_diag={"requested": 9, "with_ratio": 0, "missing": {"A": "снимката е в стария формат", "B": "снимката е в стария формат"}, "snapshot_missing_reason": ""})
assert u[0]["source"] == "unusual_options" and "снимката е в стария формат" in u[0]["message"] and "НЕ значи нормален обем" in u[0]["message"]
assert data_warnings.collect(None, None, uov_diag={"requested": 9, "with_ratio": 3, "missing": {}}) == [] and data_warnings.collect(None, None, uov_diag={"requested": 0}) == []
print("  ✓ провал → банер 'маркерите INS✓ липсват…'; остарял → 'от тегленето на <дата>'; легитимна нула и ok — без банер; UOV✓ без нито едно съотношение → банер с причината")

print()
print("── маркери върху картите и позициите; секцията отпада ──")
row = copy.deepcopy(next(c for c in B05["watchlist"] if c["ticker"] == "EXPD"))
row["markers"] = []
enrich._apply_markers(row, {"mf": set(), "uov": {}, "splits": {}, "si": {}, "si_new": {}, "ins": {"EXPD": {**REAL["TFC"], "ticker": "EXPD"}}})
assert [x["tag"] for x in row["markers"]] == ["INS✓"]
brief = copy.deepcopy(B05)
for c in brief["watchlist"]:
    if c["ticker"] == "EXPD":
        c["markers"] = row["markers"]
page = htmllib.unescape(render.render_dashboard(brief))
assert "INS✓" in page and "Lyons Michael P." in page and "общо $1.0M от 1 инсайдър" in page
old_page = htmllib.unescape(render.render_dashboard(copy.deepcopy(B02)))
assert "Insider Buying · Form 4" not in old_page and "Insider Buying" not in old_page.split("<h2>Исторически архив</h2>")[0].split("</style>")[-1]
print("  ✓ картата на EXPD (РЕАЛНА, 05.10) показва INS✓ с текста; РЕАЛНИЯТ бриф от 02.10 (6 реда в стария списък) се рендира без секцията 'Insider Buying · Form 4'")

calls = []
real_ifor = ib.insider_for
ib.insider_for = lambda tk, today=None, min_value=None: (calls.append(list(tk)) or ({"AAA": g["AAA"]}, {"kind": "ok"}))
rows = [{"ticker": "AAA"}, {"ticker": "BBB", "markers": [{"tag": "UOV✓", "title": "x"}]}, {"ticker": "AAA", "also_action": True}]
st = brief_main.attach_position_insider(rows)
assert calls == [["AAA", "BBB"]] and st == {"kind": "ok"} and [m["tag"] for m in rows[0]["markers"]] == ["INS✓"] and [m["tag"] for m in rows[1]["markers"]] == ["UOV✓"]
assert [m["tag"] for m in rows[2]["markers"]] == ["INS✓"] and brief_main.attach_position_insider([]) == {}
ib.insider_for = real_ifor
print("  ✓ позициите (отворени, чакащи, buy-stop) получават INS✓ с ЕДНО теглене за всички тикъри; съществуващите маркери се запазват")

print()
print("── main.run (структурно) ──")
tree = ast.parse((ROOT / "src" / "main.py").read_text(encoding="utf-8"))
run = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run")
called = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, (ast.Attribute, ast.Name))}
keys = [k.value for n in ast.walk(run) if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
assert "fetch_insider_buying" not in called and "attach_position_insider" in called
assert "insider_buying" not in keys and {"insider_buying_status", "insider_buying_positions_status"} <= set(keys)
print("  ✓ run() вече не вика fetch_insider_buying (скенерът на целия универс отпада); brief има insider_buying_status и insider_buying_positions_status, няма insider_buying")

print()
print("Всички тестове минаха.")
