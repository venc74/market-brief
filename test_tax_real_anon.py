"""
13.11.2026 (tax-real-fix): РЕАЛНИЯТ формат на IBKR отчет — tests/fixtures/tax/real_anon/ (четири истински отчета на потребителя, АНОНИМИЗИРАНИ с tools/tax_anonymize.js; бележката за
произхода — README.md там).
ПРОИЗХОД НА ВХОДОВЕТЕ (правило 7 на CLAUDE.md), по раздели:
  1 · РЕАЛЕН ФОРМАТ, анонимни стойности — бял списък върху real_anon (без node);
  2 · РЕАЛЕН ФОРМАТ, анонимни стойности — броеве и сметки на калкулатора върху real_anon (курсове: docs/eurofxref-hist.csv);
  3 · РЕАЛЕН ФОРМАТ, анонимни стойности — старата логика (docs/tax-v1.html) върху същите файлове;
  4 · СИНТЕТИЧЕН комбиниран отчет (две сметки, без колона Account) — построен тук;
  5 · СИНТЕТИЧНИ входове (tests/fixtures/tax/U1111111_*.csv) през анонимизатора.
Без мрежа. Разделите 2–5 са през node (tests/tax_driver.js scenario, tools/*.js) — без node SKIP; раздел 1 е чист Python.
Пускане: python test_tax_real_anon.py
"""
import csv, datetime, io, json, pathlib, re, shutil, subprocess, sys, tempfile
ROOT = pathlib.Path(__file__).parent
FX = ROOT / "tests" / "fixtures" / "tax"
RA = FX / "real_anon"
NODE = shutil.which("node")
ECB = ROOT / "docs" / "eurofxref-hist.csv"

# ── 1. бял списък: всяка клетка с текст във всеки анонимен файл е етикет или измислена стойност ─────────────────────────────────────
print("── 1. бял списък върху real_anon: нищо лично не е останало (РЕАЛЕН формат, анонимни стойности) ──")
LABEL_COLS = {"DataDiscriminator", "Asset Category", "Asset Class", "Currency", "Code", "Code (Cont.)", "Type", "Field Name", "Subtitle", "Currency Summary", "Listing Exch", "Delivery Month",
              "Direction", "Meaning", "Meaning (Cont.)"}
SAFE = re.compile(r"^[A-Za-z&/;.,()\- ]{0,48}$")
NUM = re.compile(r"^[-+]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?%?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DT = re.compile(r"^\d{4}-\d{2}-\d{2}, \d{2}:\d{2}:\d{2}$")
SYM = re.compile(r"^(Z[A-Z]{3}|[A-Z]{3}\.[A-Z]{3}|Total|SubTotal)$")
ACCT = re.compile(r"^X\d{7}( \(Anonymous Person\))?$")
ACCTS = re.compile(r"^X\d{7}(, X\d{7})*$")
ISIN = r"USZ\d{8}0"
DESC = [re.compile(rf"^Z[A-Z]{{3}}\({ISIN}\) (Cash Dividend USD \d\.\d\d per Share( - US Tax| \(Ordinary Dividend\))|Payment in Lieu of Dividend \(Ordinary Dividend\))$"),
        re.compile(rf"^Z[A-Z]{{3}}\({ISIN}\) Split \d+(\.\d+)? for \d+(\.\d+)? \(Z[A-Z]{{3}}, SYNTHETIC INSTRUMENT \d+, {ISIN}\)$"),
        re.compile(rf"^Z[A-Z]{{3}}\({ISIN}\) Corporate action REMOVED$"),
        re.compile(r"^[A-Z]{3} (Credit|Debit) Interest for [A-Z][a-z]{2}-\d{4}$"), re.compile(r"^[A-Z]{3} IBKR Managed Securities \(SYEP\) Interest for [A-Z][a-z]{2}-\d{4}$"), re.compile(r"^SYNTHETIC INSTRUMENT \d+$")]
GENERIC = {"REMOVED", "TEXT", "Alias", "Anonymous Person", "--", "-", "---"}
PERIOD = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4} - [A-Z][a-z]+ \d{1,2}, \d{4}$")
BROKER = re.compile(r"^Interactive Brokers [A-Za-z .()]{0,80}$")                     # името на брокера (етикет на отчета) — единственият дълъг етикет, който остава
HEADER_OK = re.compile(r"^[A-Za-z0-9 &/;.,()%'+\-]*$")


def allowed(sec, name, v):
    if v == "" or v in GENERIC or NUM.match(v) or DATE.match(v) or DT.match(v) or SYM.match(v) or ACCT.match(v) or ACCTS.match(v) or re.fullmatch(ISIN, v) or any(d.match(v) for d in DESC):
        return True
    if name in LABEL_COLS and SAFE.match(v):
        return True
    if sec in ("Statement", "Account Information") and name == "Field Value" and (SAFE.match(v) or PERIOD.match(v) or BROKER.match(v)):
        return True
    return False


files = sorted(RA.glob("*.csv"))
names = [f.name for f in files]
# 14.11.2026: файловете се именуват по ИЗМЕСТЕНИЯ период (месец и година на началото и края); подредбата по име = подредбата по период: три отчета, вторият от които е комбиниран с две сметки, и обобщението
assert len(files) == 4 and re.fullmatch(r"ibkr_statement_\d{6}_\d{6}\.csv", names[0]) and re.fullmatch(r"ibkr_statement_\d{6}_\d{6}\.csv", names[1]) \
    and re.fullmatch(r"ibkr_statement_\d{6}_\d{6}_2accounts\.csv", names[2]) and re.fullmatch(r"ibkr_summary_\d{6}_\d{6}\.csv", names[3]), names
bad, n_cells, n_rows = [], 0, 0
for f in files:
    raw = f.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf", f.name + ": BOM е като в оригинала"
    head = {}
    for row in csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")):
        if len(row) < 2:
            bad.append((f.name, "(ред)", "(ред)")); continue
        sec, typ = row[0], row[1]
        if typ == "Header":
            head[sec] = row[2:]
            if not all(HEADER_OK.match(c) for c in row[2:]):
                bad.append((f.name, sec, "заглавен ред"))
            continue
        n_rows += 1
        for i, v in enumerate(row[2:]):
            n_cells += 1
            name = head.get(sec, [])[i] if i < len(head.get(sec, [])) else ""
            if not allowed(sec, name, v):
                bad.append((f.name, sec, name or "(без име)"))                  # стойността НЕ се печата — тестът би я показал в публичен CI лог
assert not bad, f"{len(bad)} клетки извън белия списък (файл, секция, колона): {sorted(set(bad))[:8]}"
print(f"  ✓ {n_rows} реда, {n_cells} клетки: всяка е число, дата, етикет от бял списък или измислена стойност (Zxxx, X0000001, Anonymous Person, REMOVED, шаблонно описание)")
text_all = "\n".join(f.read_text(encoding="utf-8-sig") for f in files)
assert not re.search(r"\bU\d{6,}\b|@|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+", text_all), "истински номер на сметка / имейл"
print("  ✓ няма номер на сметка (U + цифри) и имейл")

if not NODE:
    print("SKIP: няма node — разделите 2–5 не са изпълнени (в CI node има)"); sys.exit(0)


def scenario(files, years=(), **settings):
    p = subprocess.run([NODE, str(ROOT / "tests" / "tax_driver.js"), "scenario"], input=json.dumps({"files": files, "years": list(years), "settings": settings}), capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    out = json.loads(p.stdout)
    for k in ("de", "summary", "whyZero"):
        out[k] = {int(y): v for y, v in out[k].items()}
    return out


def realized(o, y):
    R = [x for x in o["fifo"]["realized"] if x["year"] == y]
    return {"n": len(R), "pos": sum(1 for x in R if x["gainEUR"] is not None and x["gainEUR"] > 0), "neg": sum(1 for x in R if x["gainEUR"] is not None and x["gainEUR"] < 0)}


def recon_by_account(o, y):
    c = {}
    for m in o["de"][y].get("reconcile", []):
        c[m["account"]] = c.get(m["account"], 0) + 1
    return c


# ── 2. калкулаторът върху реалния формат ──────────────────────────────────────────────────────────────────────────────────────────
if not ECB.exists():
    print("SKIP: няма docs/eurofxref-hist.csv — раздел 2 не е изпълнен (курсовете идват от него)")
else:
    print("── 2. калкулаторът върху реалния формат (РЕАЛЕН формат, анонимни стойности; курсове — docs/eurofxref-hist.csv) ──")
    inp = [{"name": f.name, "text": f.read_text(encoding="utf-8")} for f in files] + [{"name": "ecb.csv", "text": ECB.read_text(encoding="utf-8")}]
    YS = list(range(2016, 2026))                                                                         # 14.11.2026: датите в копието са изместени с цели месеци — данните са за 2017–2022; годините по-долу са на КОПИЕТО
    o = scenario(inp, years=YS)
    ib = [f for f in o["files"] if f["format"] == "ibkr"]
    assert [f["records"] for f in ib] == [70, 124, 188, 105], [f["records"] for f in ib]               # 124 и 188 = със 8 + 2 реда Transfers (записи „xfer“ от 13.11)
    assert all(not [p for p in f["problems"] if p["level"] == "err"] for f in ib), "истинският формат не бива да дава червено съобщение за файл"
    print("  ✓ и четирите файла са разпознати като IBKR: 70 / 124 / 188 / 105 записа (вкл. Transfers), без червено съобщение за файл")
    A1, A2 = "X0000001", "X0000002"
    by = {}
    for r in o["records"]:
        if r["kind"] == "trade":
            by[(r["src"], r["account"])] = by.get((r["src"], r["account"]), 0) + 1
    assert by == {(names[0], A1): 67, (names[1], A1): 116, (names[2], A1): 132, (names[2], A2): 45, (names[3], A2): 87}, by
    print("  ✓ комбинираният отчет (без колона Account в Trades): 132 сделки на първата сметка и 45 на втората — до 13.11 и 177-те отиваха към ПОСЛЕДНАТА сметка във файла")
    f = o["fifo"]
    assert f["controlsApplied"] is True
    # периодите — от самите файлове: краят на третия отчет и началото на четвъртия (между тях липсва период)
    def period(text):
        m = re.search(r'Statement,Data,Period,"([A-Za-z]+ \d+, \d{4}) - ([A-Za-z]+ \d+, \d{4})"', text)
        return [datetime.datetime.strptime(x, "%B %d, %Y").date() for x in m.groups()]
    end3, start4 = period(files[2].read_text(encoding="utf-8"))[1], period(files[3].read_text(encoding="utf-8"))[0]
    gap_from, gap_to = end3 + datetime.timedelta(days=1), start4 - datetime.timedelta(days=1)
    assert (gap_to - gap_from).days > 300
    log = sorted((c["type"], c["year"], c["account"]) for c in f["controlLog"])
    assert log == [("start", start4.year, A2), ("start", start4.year, A2)], log                    # смяната на тикъра (един Conid) не дава нито излишък, нито липса
    drop = [c for c in f["controlLog"] if c["year"] == start4.year]
    assert all(c["reported"] == 0 and c["positions"] == 0 and c["gapYears"] == [] and c["gapPeriod"] == {"from": gap_from.isoformat(), "to": gap_to.isoformat()} for c in drop) and len(drop) == 2
    print("  ✓ контрол в началото на четвъртия отчет (втората сметка): започва с 0 позиции → 2 тикъра с лотове от по-стар отчет не се ползват; липсващият период (повече от година) е показан с датите си")
    assert not [x for x in f["realized"] if x["date"] >= start4.isoformat() and any(l["date"] < start4.isoformat() for l in x["lots"])]
    dmy = lambda d: d.strftime("%d.%m.%Y")
    assert any(f"Между отчетите липсва период от {dmy(gap_from)} до {dmy(gap_to)}" in n and "започва без отворени позиции" in n for n in [m["text"] for m in o["de"][start4.year]["notes"]])
    print("  ✓ годината на четвъртия отчет показва съобщението „Между отчетите липсва период от … до … — … защото отчетът започва без отворени позиции“ (периодът не е цяла календарна година — друго съобщение от „липсва година“)")
    assert f["endChecks"] == [], f["endChecks"]
    print("  ✓ край на отчет: 0 разлики за ВСЯКА година и сметка — Inter-Company пренася лотовете към втората сметка, а първата (затворена) е на 0")
    acats = set(re.findall(r"Transfers,Data,[^\n]*?,(\d{4}-\d\d-\d\d),ACATS,In", files[1].read_text(encoding="utf-8")))
    assert len(acats) == 1, acats
    assert [(x["kind"], x["date"]) for x in f["pending"]] == [("acats", acats.pop())] * 8 and all(not x["filled"] for x in f["pending"])
    print("  ✓ 8 × ACATS „In“ (от друг брокер) = 8 лота без покупна цена за ръчно въвеждане — и нищо друго")
    assert any("един и същ инструмент (Conid" in w and "смяна на тикъра" in w for w in o["warnings"]) and len(o["warnings"]) == 1
    print("  ✓ смяна на тикър без ред в отчета (един и същ Conid в два отчета): лотовете на стария тикър продължават под новия; съобщение с двата тикъра")
    assert f["unmatched"] == [] and f["open"] == []
    exp = {2017: (9, 0, True), 2018: (30, 1, False), 2019: (54, 6, False), 2020: (24, 1, False), 2021: (26, 0, True), 2022: (12, 0, True)}      # общо 155 = 19 + 37 + 54 + 38 + 7 разделени продажби (продажба от лот без цена И от лотове с цена е два реда — известната част има резултат)
    assert sum(n for n, _, _ in exp.values()) == len(f["realized"]) == 155
    for y, (n, nul, complete) in exp.items():
        R = [x for x in f["realized"] if x["year"] == y]
        assert len(R) == n and sum(1 for x in R if x["gainEUR"] is None) == nul and sum(1 for x in R if x.get("unknownLots")) == nul, (y, len(R))
        assert o["de"][y]["complete"] is complete and o["de"][y]["headline"] > 0, y
    print("  ✓ продажби 9 / 30 / 54 / 24 / 26 / 12 по години на копието (155 общо); без резултат (лот без покупна цена — не „липсва покупка“, не нула) само в трите години с ACATS продажби (1, 6 и 1); тези три са НЕПЪЛНО до въвеждането на цените")
    d25 = o["de"][2025]
    assert d25["headline"] == 0 and "няма нито един запис за 2025" in o["whyZero"][2025][0] and o["summary"][2025]["year"]["records"] == 0
    print("  ✓ година без отчет: числото е 0 и калкулаторът го казва („няма нито един запис за …“) — не тиха нула")

    # ── 3. старата логика ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    print("── 3. старата логика (tax-v1, чете по ПОЗИЦИЯ) върху същите файлове (РЕАЛЕН формат, анонимни стойности) ──")
    p = subprocess.run([NODE, str(ROOT / "tools" / "tax_diagnose.js"), "--rates", str(ECB)] + [str(f) for f in files], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-1500:]
    old = p.stdout.split("СТАРАТА ЛОГИКА", 1)[1].split("НОВАТА ЛОГИКА", 1)[0]
    assert old.count("няма намерени сделки с акции") == 3, old[:600]
    assert old.count("[5] = Symbol · [6] = Date/Time · [7] = Quantity · [8] = T. Price") >= 3 and "[5] = Account · [6] = Symbol · [7] = Date/Time · [8] = Quantity · [9] = T. Price" in old
    assert "Stocks / ETF 67 → с количество, цена и дата 0" in old and "Stocks / ETF 116 → с количество, цена и дата 0" in old and "Stocks / ETF 177 → с количество, цена и дата 0" in old
    assert "Stocks / ETF 85 → с количество, цена и дата 85" in old and "покупки 49 · продажби 36" in old
    print("  ✓ първите три отчета (14 колони, без Account): старата очаква Symbol на [6], а той е на [5] → 0 валидни сделки от 67 / 116 / 177 (причината за нулата на tax-v1)")
    print("  ✓ четвъртият отчет (15 колони, Account след Currency): старата чете 85 сделки (49 покупки, 36 продажби)")

# ── 4. комбиниран отчет с две сметки, без колона Account (СИНТЕТИЧЕН) ─────────────────────────────────────────────────────────────
print("── 4. комбиниран отчет с две сметки, без колона Account в Trades (СИНТЕТИЧЕН — построен тук; формата е по реалния отчет за 2024) ──")
TRH = "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
OPH = "Open Positions,Header,DataDiscriminator,Asset Category,Currency,Symbol,Quantity,Mult,Cost Price,Cost Basis,Close Price,Value,Unrealized P/L,Code"


def block(acct, trades, opens):
    return ["Statement,Header,Field Name,Field Value", "Statement,Data,BrokerName,Interactive Brokers Ireland Limited", "Statement,Data,Title,Activity Statement",
            'Statement,Data,Period,"January 1, 2024 - December 31, 2024"', "Account Information,Header,Field Name,Field Value", f"Account Information,Data,Account,{acct}",
            "Account Information,Data,Base Currency,EUR", TRH] + trades + [OPH] + opens


def t(sym, d, q, p):
    return f'Trades,Data,Order,Stocks,USD,{sym},"{d}, 10:00:00",{q},{p},{p},{-q * p},-1,{q * p + 1},0,0,{"O" if q > 0 else "C"}'


def op(sym, q):
    return f"Open Positions,Data,Summary,Stocks,USD,{sym},{q},1,100,{q * 100},100,{q * 100},0,"


def combined(open_b_aaa):
    return "\n".join(block("U2222222", [t("AAA", "2024-02-05", 10, 100)], [op("AAA", 10)]) + block("U3333333", [t("AAA", "2024-03-05", 5, 110), t("BBB", "2024-03-06", 7, 50)], [op("AAA", open_b_aaa), op("BBB", 7)])) + "\n"


rates = "Date,USD\n2024-12-31,1.10\n2024-03-06,1.10\n2024-03-05,1.10\n2024-02-05,1.10\n"
o = scenario([{"name": "c.csv", "text": combined(5)}, {"name": "ecb.csv", "text": rates}], years=[2024])
acc = sorted((r["sym"], r["account"], r["qty"]) for r in o["records"] if r["kind"] == "trade")
assert acc == [("AAA", "U2222222", 10), ("AAA", "U3333333", 5), ("BBB", "U3333333", 7)], acc
print("  ✓ сметката на всяка сделка е от „Account Information“ на нейния блок: AAA 10 → U2222222; AAA 5 и BBB 7 → U3333333")
assert o["de"][2024].get("reconcile", []) == [], o["de"][2024].get("reconcile")
print("  ✓ наличностите от Open Positions на всеки блок съвпадат с FIFO на СВОЯТА сметка → 0 разлики (до 13.11 всичко беше на последната сметка и излизаха фалшиви разлики)")
o = scenario([{"name": "c.csv", "text": combined(6)}, {"name": "ecb.csv", "text": rates}], years=[2024])
rec = o["de"][2024].get("reconcile", [])
assert [(m["account"], m["sym"], m["reported"], m["computed"]) for m in rec] == [("U3333333", "AAA", 6, 5)], rec
print("  ✓ истинска разлика (6 вместо 5 при втората сметка) се показва точно при нея и в никоя друга")
o = scenario([{"name": "c.csv", "text": combined(5).replace("Account Information,Data,Account,U3333333", "Account Information,Data,Account,U3333333 (Test Person)")}, {"name": "ecb.csv", "text": rates}], years=[2024])
assert {r["account"] for r in o["records"] if r["kind"] == "trade"} == {"U2222222", "U3333333"}
print("  ✓ „U3333333 (Test Person)“ — името в скоби не влиза в номера на сметката")

# ── 5. анонимизаторът върху СИНТЕТИЧНИ входове ────────────────────────────────────────────────────────────────────────────────────
print("── 5. tools/tax_anonymize.js върху СИНТЕТИЧНИ входове (tests/fixtures/tax/U1111111_*.csv) ──")
import datetime
SRC = ["U1111111_2020.csv", "U1111111_2021.csv", "U1111111_2022.csv", "U1111111_2023.csv", "U1111111_2026.csv"]
SECRET = ["ACME", "XWLD", "SPLT", "OLDCO", "GHOST", "LOSSCO", "DIVCO", "EQETF", "U1111111", "Test Person", "NYSE Market Data", "US00000000A1", "SYNTH WORLD"]
# 14.11.2026: датите в копието са изместени с цели месеци назад — курсовете трябва да покриват и по-ранните години; константен курс (1.10) за двата прогона, за да се сравняват резултатите само по логика
CONST = "Date,USD,JPY,GBP,CHF\n" + "".join(f"{(datetime.date(2012, 1, 1) + datetime.timedelta(days=i)).isoformat()},1.10,1.0,1.0,1.0\n" for i in range(0, 365 * 19))
with tempfile.TemporaryDirectory() as tmp:
    tmp = pathlib.Path(tmp)
    (tmp / "in").mkdir()
    for n in SRC:
        shutil.copy(FX / n, tmp / "in" / n)
    (tmp / "in" / "standard.csv").write_text((FX / "broker2_export.csv").read_text(encoding="utf-8"), encoding="utf-8")        # не е IBKR отчет → пропуска се

    def anon(indir, out, *extra):
        p = subprocess.run([NODE, str(ROOT / "tools" / "tax_anonymize.js"), str(tmp / indir), str(tmp / out), *extra], capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr[-1500:]
        return p.stdout

    msg = anon("in", "o7", "--seed", "7")
    assert "записани 5 анонимни файла" in msg and "пропуснати (не са IBKR отчет): 1" in msg and "сплитове: 1" in msg, msg
    outs = sorted((tmp / "o7").glob("*.csv"))
    assert len(outs) == 5, [f.name for f in outs]
    blob = "\n".join(f.read_text(encoding="utf-8-sig") for f in outs)
    leaked = [s for s in SECRET if s in blob]
    assert not leaked, leaked
    print("  ✓ нито един измислен тикър, сметка, име или описание от входа не е в изхода; файл, който не е IBKR отчет, се пропуска")

    # ── датите: ЕДИН общ отместител в цели месеци назад; всяка дата в копието = датата от входа + K месеца (денят се пази, а ако го няма — последният ден на месеца) ──
    def shift(d, K):
        y, m, dd = map(int, d.split("-")); t = y * 12 + (m - 1) + K; ny, nm = divmod(t, 12); nm += 1
        last = (datetime.date(ny + (nm == 12), nm % 12 + 1, 1) - datetime.timedelta(days=1)).day
        return f"{ny}-{nm:02d}-{min(dd, last):02d}"

    def cells(path, sections):
        out, head = [], {}
        for row in csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"), newline="")):
            if len(row) < 2: continue
            if row[1] == "Header": head[row[0]] = row[2:]; continue
            if row[0] in sections and row[1] == "Data":
                for name, v in zip(head[row[0]], row[2:]):
                    m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:, \d\d:\d\d:\d\d)?$", v)
                    if m and not (row[0] == "Corporate Actions"): out.append(m.group(1))
        return out
    SEC = {"Trades", "Dividends", "Withholding Tax", "Interest", "Transfers"}
    # входните файлове и изходните — по реда на периода (файловете са по една година; изходът се подрежда по изместения период)
    ins = sorted(SRC)
    out_by_period = sorted(outs, key=lambda f: f.name)
    assert len(ins) == len(out_by_period) == 5
    Ks = set()
    for n, f in zip(ins, out_by_period):
        a, b = cells(FX / n, SEC), cells(f, SEC)
        assert len(a) == len(b) and a, (n, len(a), len(b))
        for x, y in zip(a, b):
            ky = (int(y[:4]) * 12 + int(y[5:7])) - (int(x[:4]) * 12 + int(x[5:7]))
            Ks.add(ky)
    assert len(Ks) == 1, Ks                                                                   # ЕДИН общ отместител за всички дати и всички файлове
    K = Ks.pop()
    assert -60 <= K <= -15 and K % 12 != 0, K
    for n, f in zip(ins, out_by_period):
        assert [shift(x, K) for x in cells(FX / n, SEC)] == cells(f, SEC), n                    # точно K месеца, денят се пази
    per_in = [re.search(r'Statement,Data,Period,"([^"]+)"', (FX / n).read_text(encoding="utf-8")).group(1) for n in ins]
    per_out = [re.search(r'Statement,Data,Period,"([^"]+)"', f.read_text(encoding="utf-8-sig")).group(1) for f in out_by_period]
    MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    def long_shift(s, K):
        def one(m):
            d = shift(f"{m.group(3)}-{MONTHS.index(m.group(1)) + 1:02d}-{int(m.group(2)):02d}", K); y, mo, dd = d.split("-")
            return f"{MONTHS[int(mo) - 1]} {int(dd)}, {y}"
        return re.sub(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", one, s)
    assert [long_shift(x, K) for x in per_in] == per_out, (per_in, per_out)
    print("  ✓ датите: един общ отместител (цели месеци назад, не кратно на 12) за ВСИЧКИ дати в сделки, дивиденти, лихви и периода на отчета; денят от месеца се пази; файловете се именуват по изместения период")
    # ── сплитът: нов коефициент (A·m, m = 2…9), датата — допълнително на случаен ден между последната сделка преди него и първата след него ──
    sp = re.findall(r"Split (\d+) for (\d+) \(", blob)
    assert len(sp) == 1 and sp[0][1] == "1" and int(sp[0][0]) in range(8, 37, 4), sp                  # 4 за 1 → 4·m за 1, m = 2…9
    day = re.search(r'Corporate Actions,Data,Stocks,EUR,X\d+,(\d{4}-\d\d-\d\d),"(\d{4}-\d\d-\d\d), (\d\d:\d\d:\d\d)"', blob)
    lo, hi = shift("2022-01-10", K), shift("2023-03-01", K)                                      # последна сделка преди сплита (покупка) и първа след него (продажба)
    assert lo <= day.group(2) <= hi and day.group(1) >= day.group(2), (lo, day.group(2), hi)
    moved = set()
    for sd in ("1", "2", "3", "4", "5", "6"):
        anon("in", "s" + sd, "--seed", sd, "--shift-months", "-20")
        b = "\n".join(f.read_text(encoding="utf-8-sig") for f in sorted((tmp / ("s" + sd)).glob("*.csv")))
        d2 = re.search(r'Corporate Actions,Data,Stocks,EUR,X\d+,(\d{4}-\d\d-\d\d),"(\d{4}-\d\d-\d\d), (\d\d:\d\d:\d\d)"', b).group(2)
        assert shift("2022-01-10", -20) <= d2 <= shift("2023-03-01", -20), d2
        moved.add(d2 != shift("2022-06-01", -20))
    assert True in moved, "датата на сплита трябва да се мести допълнително на случаен ден (поне при един от 6 seed)"
    print("  ✓ сплит 4 за 1 → 4·m за 1 (m = 2…9); датата му е между изместените дати на последната сделка преди него и първата след него (при 6 seed — местена допълнително)")
    # ── оригиналът и копието през калкулатора: ЕДНАКВИ резултати (изместване точно −24 месеца → годините са −2; константен курс) ──
    anon("in", "o24", "--seed", "11", "--shift-months", "-24")
    outs24 = sorted((tmp / "o24").glob("*.csv"), key=lambda f: f.name)
    ys = (2020, 2021, 2022, 2023, 2026)
    o1 = scenario([{"name": n, "text": (FX / n).read_text(encoding="utf-8")} for n in sorted(SRC)] + [{"name": "ecb.csv", "text": CONST}], years=ys)
    o2 = scenario([{"name": f.name, "text": f.read_text(encoding="utf-8-sig")} for f in outs24] + [{"name": "ecb.csv", "text": CONST}], years=[y - 2 for y in ys])
    for y in ys:
        assert realized(o1, y) == realized(o2, y - 2), (y, realized(o1, y), realized(o2, y - 2))
        s1, s2 = o1["de"][y], o2["de"][y - 2]
        assert (s1["headline"] > 0) - (s1["headline"] < 0) == (s2["headline"] > 0) - (s2["headline"] < 0) and s1["complete"] == s2["complete"], y
    assert len(o1["fifo"]["unmatched"]) == len(o2["fifo"]["unmatched"]) and len(o1["fifo"]["open"]) == len(o2["fifo"]["open"])
    assert [len(o1["fifo"][k]) for k in ("controlLog", "endChecks", "pending")] == [len(o2["fifo"][k]) for k in ("controlLog", "endChecks", "pending")]
    assert sum(realized(o1, y)["n"] for y in ys) > 0, "сравнението не е празно"
    print("  ✓ оригиналът и копието (изместване −24 месеца, сплит 4 → 4·m за 1) през калкулатора: същите продажби (печалба / загуба), без покупка, отворени позиции, контроли, знак и „пълно“ по години")
    anon("in", "o7b", "--seed", "7")
    assert all((tmp / "o7" / f.name).read_bytes() == (tmp / "o7b" / f.name).read_bytes() for f in outs), "един и същ --seed → същите байтове"
    anon("in", "o9", "--seed", "9")
    assert "\n".join(f.read_text(encoding="utf-8-sig") for f in outs) != "\n".join(f.read_text(encoding="utf-8-sig") for f in sorted((tmp / "o9").glob("*.csv"))), "друг --seed → други множители"
    print("  ✓ един и същ --seed дава същите байтове, друг — други множители, отместител и коефициенти (без --seed са случайни от crypto)")
    (tmp / "bomin").mkdir()
    (tmp / "bomin" / "x.csv").write_bytes(b"\xef\xbb\xbf" + (FX / SRC[0]).read_bytes())
    anon("bomin", "ob", "--seed", "7")
    assert [f.read_bytes()[:3] for f in (tmp / "ob").glob("*.csv")] == [b"\xef\xbb\xbf"] and all(f.read_bytes()[:3] != b"\xef\xbb\xbf" for f in outs)
    print("  ✓ BOM се пази там, където го има в оригинала (и не се добавя там, където го няма)")
print("test_tax_real_anon: ВСИЧКО ОК")
