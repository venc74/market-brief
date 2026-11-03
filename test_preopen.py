"""
03.11.2026 · т. 10 (решения от 03.11): обновяването ПРЕДИ ОТВАРЯНЕТО — src/preopen.py, отделна стъпка в options_record.yml (09:05 Ню Йорк); без AI — 8-K точките и заглавието
дословно; карето стои до следващия сутрешен бриф; имейл само ако има нещо. Сутрешният бриф (01:30 Ню Йорк) не вижда премаркета: на 03.11 EP сутрин видя FN, а в 09:05 Ню Йорк
в премаркета имаше LSCC +13.5% и AEIS +12.5% (8-K т. 2.02 и за двете, след затварянето на 02.11). Отварянето: LSCC +13.15%, AEIS +7.11%.

РЕАЛНО: tests/fixtures/preopen_2026-11-03.json.gz (бележката — вътре): 5-минутните бари с премаркет на LSCC, AEIS, FN, ELF, CRCL (02.11 09:30 – 03.11 10:00 Ню Йорк), дневните бари
на LSCC и AEIS, 8-K-тата им след затварянето на 02.11 и заглавието за AEIS до 09:05; tests/fixtures/brief_2026-10-19.json — рамката на страницата.
СИНТЕТИЧНО (означено): „сега“ (09:05 Ню Йорк — барите след него се режат), картите и записите за нивата в т. 4, подменените 8-K / заглавия / дневни функции (връщат РЕАЛНИТЕ),
имейлът (не се праща).
Пускане: python test_preopen.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_preopen_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import preopen, render, options_record, qm_ep

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "preopen_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
WB = json.loads((ROOT / "tests" / "fixtures" / "preopen_watch_brief_2026-11-03.json").read_text(encoding="utf-8"))      # РЕАЛНО: brief["watch"] на 03.11 (цената)
NOW = dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.timezone.utc)                     # СИНТЕТИЧНО: 09:05 Ню Йорк (EST) = 15:05 Берлин
q = lambda: contextlib.redirect_stdout(io.StringIO())
frames = {t: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["t"], utc=True)) for t, b in FX["bars_5m"].items()}
daily = {t: pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["d"])) for t, d in FX["daily"].items()}

print("── 1. premarket_point — РЕАЛНИТЕ 5-минутни бари; всичко след 09:05 Ню Йорк се реже ──")
l = preopen.premarket_point(frames["LSCC"], NOW)
assert (l["session"], round(l["prev_close"], 2), round(l["pm_price"], 2), l["pm_last_ny"]) == ("2026-11-02", 95.43, 108.32, "09:00"), l      # последният редовен 5-мин. бар
a = preopen.premarket_point(frames["AEIS"], NOW)
assert (round(a["pm_price"], 2), a["pm_last_ny"]) == (244.3, "08:40") and a["pm_volume"] is None                          # обемът в премаркета — 0 при Yahoo
assert preopen.premarket_point(frames["LSCC"], NOW + dt.timedelta(minutes=20))["pm_last_ny"] == "09:20"                   # в 09:25 барът от 09:25 още не е затворен
later = preopen.premarket_point(frames["LSCC"], NOW + dt.timedelta(minutes=40))
assert later["pm_last_ny"] == "09:25" and later["pm_bars"] > l["pm_bars"]                                                  # в 09:45 — до 09:25; редовната сесия не е премаркет
assert preopen.premarket_point(frames["LSCC"], dt.datetime(2026, 11, 3, 8, 0, tzinfo=dt.timezone.utc)) is None             # 03:00 Ню Йорк — няма премаркет още
print(f"  ✓ LSCC: последният редовен бар на 02.11 $95.43 → премаркет $108.32 в 09:00; AEIS $244.30 в 08:40; обемът в премаркета — 0 (Yahoo); след 09:30 — нищо ново")

print()
print("── 2. scan + ep_rows — гаповете ≥ +10%, пренебрегването, 8-K и заглавието (СИНТЕТИЧНО: функциите връщат РЕАЛНИТЕ данни) ──")
pts, gaps, diag = preopen.scan(frames, NOW)
assert [g["ticker"] for g in gaps] == ["LSCC", "AEIS"] and diag["gappers"] == 2 and diag["zero_volume_share"] == 1.0
assert round(gaps[1]["prev_close"], 2) == 216.74 and round(gaps[1]["gap_pct"], 2) == 12.72                                 # прагът — по последния 5-мин. бар
assert round(pts["FN"]["pm_price"] / pts["FN"]["prev_close"] - 1, 3) < 0.10                                                 # FN (сутрешният EP) — под 10% в 09:05
calls = []
rows = preopen.ep_rows(gaps, daily_fn=lambda ts: {t: daily[t] for t in ts}, filings_fn=lambda t, s, now_utc=None: (calls.append((t, s)), FX["filings"][t])[1],
                       headlines_fn=lambda t, since: [FX["headline_AEIS"]] if t == "AEIS" else [], now_utc=NOW)
L, A = rows
assert (L["ticker"], L["gap_pct"], L["neglect"], round(L["ret63_pct"]), L["prev_close"]) == ("LSCC", 13.5, True, -31, 95.44)
assert (A["prev_close"], A["gap_pct"]) == (217.19, 12.48)                                                                  # показаното — от официалното дневно затваряне
assert L["filings_8k"][0]["text"] == "8-K (SEC), 02.11 16:27 ET: 2.02 — финансови резултати" and L["filings_8k"][0]["items"] == ["2.02"] and L["headline"] is None
assert A["gap_pct"] == 12.48 and A["headline"]["title"] == "Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript" and A["filings_8k"][0]["text"] == "8-K (SEC), 02.11 16:03 ET: 2.02 — финансови резултати"
assert calls == [("LSCC", "2026-11-02"), ("AEIS", "2026-11-02")]
syn = {"accepted_et": "2026-11-03 07:01", "items": [(c, None, None) for c in ("1.01", "2.01", "7.01", "8.01", "5.02", "6.99")], "items_note": "по документа"}   # СИНТЕТИЧНО
assert preopen.filing_line(syn) == ("8-K (SEC), 03.11 07:01 ET: 1.01 — съществено споразумение; 2.01 — придобиване или продажба на активи; 7.01 — оповестяване по Reg FD; "
                                    "8.01 — други събития; 5.02 — смяна в ръководството; 6.99 (по документа)")
assert preopen.filing_line({"accepted_et": "2026-11-03 07:01", "items": []}).endswith("ET: без точки")
assert preopen.filing_line(FX["filings"]["LSCC"][0]) == qm_ep.filing_headline(FX["filings"]["LSCC"][0])["title"]                 # един текст и в сутрешната EP карта (т. 0б)
print("  ✓ 8-K: „2.02 — финансови резултати“ — същият ред като в сутрешната EP карта; 1.01 / 2.01 / 7.01 / 8.01 с превод, непознатата — само номерът")
print("  ✓ LSCC +13.5% (пренебрегнат, 3 мес. −31%) — 8-K т. 2.02 в 16:27 ET; AEIS +12.5% — 8-K т. 2.02 в 16:03 ET и „Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript“; FN — под 10%")

print()
print("── 3. наблюдаваните (РЕАЛНО: ELF, CRCL под ±3% в 09:05) ──")
w = preopen.watch_gaps(pts, ["ELF", "CRCL", "LSCC"])
assert [x["ticker"] for x in w] == ["LSCC"] and w[0]["gap_pct"] == 13.51                                                  # СИНТЕТИЧНО: LSCC като наблюдаван
assert preopen.watch_gaps(pts, ["ELF", "CRCL"]) == []
assert w[0]["close_src"] == "5m" and w[0]["prev_close"] == 95.43                                                             # няма го в сутрешния бриф → 5-мин. бар
cl = preopen.watch_closes(WB)
assert len(cl) == 14 and cl["ELF"] == {"close": 110.68, "date": "2026-11-02"} and cl["CRCL"]["close"] == 72.08
_thr, config.PREOPEN_WATCH_GAP_PCT = config.PREOPEN_WATCH_GAP_PCT, 0.1                                                    # СИНТЕТИЧНО: по-нисък праг, за да се видят редовете
try:
    w2 = {x["ticker"]: x for x in preopen.watch_gaps(pts, ["ELF", "CRCL"], cl)}
    assert (w2["ELF"]["prev_close"], w2["ELF"]["gap_pct"], w2["ELF"]["close_src"]) == (110.68, -0.43, "brief")           # официалното $110.68, не барът $110.63
    assert (w2["CRCL"]["prev_close"], w2["CRCL"]["gap_pct"], w2["CRCL"]["close_src"]) == (72.08, 1.17, "brief")
    stale = {**cl, "ELF": {"close": 110.68, "date": "2026-10-30"}}                                                             # СИНТЕТИЧНО: затваряне от друга сесия
    assert {x["ticker"]: x["close_src"] for x in preopen.watch_gaps(pts, ["ELF"], stale)} == {"ELF": "5m"}
finally:
    config.PREOPEN_WATCH_GAP_PCT = _thr
assert preopen.watch_closes(None) == {} and preopen.watch_closes({"watch": [{"ticker": "X", "facts": {}}]}) == {}
print("  ✓ ELF и CRCL — под ±3%; базата е официалното затваряне от сутрешния бриф (ELF $110.68, не 5-мин. бар $110.63); без него / от друга сесия — 5-мин. бар с бележка")

print()
print("── 4. нивата — само пресичанията (СИНТЕТИЧНО: картите и записите) ──")
lv = preopen.level_checks(pts, [{"ticker": "LSCC", "setup": {"buy_stop": 100.0}}], [{"ticker": "AEIS", "trigger": 250.0}],
                          [{"ticker": "FN", "category": "qm_breakout", "status": "open", "stop_loss": 10_000.0},
                           {"ticker": "ELF", "category": "buystop", "status": "pending", "buy_stop": 1.0},
                           {"ticker": "CRCL", "category": "glb_wish_high", "status": "open", "line_used": 10_000.0},
                           {"ticker": "CRCL", "category": "glb_wish", "status": "open", "line_used": 10_000.0}])
assert [(x["ticker"], x["what"], x["kind"]) for x in lv] == [("LSCC", "Чака пробив", "над нивото"), ("FN", "книга QM", "под стопа"), ("ELF", "книга buy-stop", "над нивото"),
                                                             ("CRCL", "книга GLB по Уиш", "под линията")], lv
assert lv[0]["level"] == 100.0 and lv[0]["pm_price"] == 108.32 and lv[0]["pct"] == 8.32
print("  ✓ над buy-stop / нивото, под стопа, под линията; AEIS под нивото $250 — не; архивираната „GLB — наш вариант“ — не")

print()
print("── 5. run → карето и имейлът (РЕАЛНИЯТ бриф от 19.10 като рамка) ──")
with q():
    res = preopen.run(NOW, frames5=frames, brief={}, records=[], watched=["ELF", "CRCL"], universe=list(frames),
                      daily_fn=lambda ts: {t: daily[t] for t in ts if t in daily}, filings_fn=lambda t, s, now_utc=None: FX["filings"].get(t, []),
                      headlines_fn=lambda t, since: [FX["headline_AEIS"]] if t == "AEIS" else [])
assert (res["date"], res["time_ny"], res["time_berlin"], res["session"], res["ok"]) == ("2026-11-03", "09:05", "15:05", "2026-11-02", True)
assert [g["ticker"] for g in res["gaps"]] == ["LSCC", "AEIS"] and res["levels"] == [] and res["watch"] == [] and preopen.has_news(res)
b = copy.deepcopy(B19); b["preopen"] = res
with q():
    page = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Преди отварянето (15:05 Берлин / 09:05 Ню Йорк)" in page and page.index("Преди отварянето (") < page.index("Пазарен термометър")
with q():
    hdr = render.render_dashboard(b, publish=False, generated=preopen.morning_generated("<div>понеделник · генериран 07:34 CET</div>"))
assert "генериран 07:34 CET · обновено преди отварянето 15:05 CET" in hdr                                                  # заглавието пази часа на сутрешния бриф
assert preopen.morning_generated(hdr) == ("07:34", "CET") and preopen.morning_generated(None) is None                     # и при второ пускане — пак сутрешният
assert "LSCC +13.5% ($108.32 в 09:00 Ню Йорк; затваряне $95.44) · пренебрегнат (3 мес. -31%) 8-K (SEC), 02.11 16:27 ET: 2.02 — финансови резултати" in page
assert "„Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript“" in page
mail = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", preopen.email_html(res))))
assert mail.startswith(" Преди отварянето · 03.11, 09:05 Ню Йорк (15:05 Берлин)") and "AEIS +12.5% ($244.30; затваряне $217.19) · пренебрегнат (3 мес. -36%)" in mail
assert "„Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript“ " in mail and "Transcript“ ·" not in mail                  # без празен източник
quiet = {**res, "gaps": [], "levels": [], "watch": [], "volume_note": None}
b["preopen"] = quiet
with q():
    p2 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "Нищо за отбелязване: няма гап ≥ +10% в универса" in p2 and not preopen.has_news(quiet)
b["preopen"] = {**quiet, "ok": False, "notes": ["празно"]}
with q():
    p3 = render.render_dashboard(b, publish=False)
assert "Премаркетът не се изтегли днес" in p3
b.pop("preopen")
with q():
    assert "Преди отварянето (" not in render.render_dashboard(b, publish=False)                                            # сутрешният бриф — без каре
VN = "Обемът в премаркета не е наличен (Yahoo) — провери го в първите минути"
assert res["volume_note"] == VN and f"⚠ {VN}." in page and f"⚠ {VN}." in mail                                                # РЕАЛНО: на 03.11 обемът е 0 при всички
print("  ✓ карето най-горе (преди термометъра); заглавието — „генериран 07:34 CET · обновено преди отварянето 15:05 CET“; имейлът — само при нещо; „Нищо за отбелязване“; провал — не изглежда като „нищо“; сутрешният бриф — без каре")

print()
print("── 5б. обемът в премаркета (СИНТЕТИЧНО: обемите) ──")
assert preopen.volume_note({"gaps": [{"ticker": "A", "pm_volume": 12345.0}], "watch": [{"ticker": "B", "pm_volume": None}]}) == \
    "Обемът в премаркета не е наличен (Yahoo) за B — провери го в първите минути"
assert preopen.volume_note({"gaps": [{"ticker": "A", "pm_volume": 12345.0}], "levels": [{"ticker": "A", "pm_volume": 12345.0}]}) is None
assert preopen.volume_note({"gaps": [], "levels": [], "watch": []}) is None                                                   # празно каре — без реда
v = {**res, "gaps": [{**res["gaps"][0], "pm_volume": 12345.0}], "volume_note": None}
b["preopen"] = v
with q():
    p4 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
assert "затваряне $95.44) · обем в премаркета 12 345 · пренебрегнат" in p4 and "⚠ Обемът" not in p4
assert "затваряне $95.44) · обем в премаркета 12 345 · пренебрегнат" in re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", preopen.email_html(v))))
b["preopen"] = {**res, "gaps": [], "watch": [{"ticker": "ELF", "gap_pct": -3.2, "pm_price": 107.1, "prev_close": 110.63, "close_src": "5m", "pm_last_ny": "09:00", "pm_volume": None},
                                       {"ticker": "CRCL", "gap_pct": 4.0, "pm_price": 74.96, "prev_close": 72.08, "close_src": "brief", "pm_last_ny": "09:00", "pm_volume": None}]}   # СИНТЕТИЧНО
with q():
    p5 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", render.render_dashboard(b, publish=False))))
m5 = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", preopen.email_html(b["preopen"]))))
for txt in (p5, m5):
    assert "ELF -3.2% ($107.10; затваряне $110.63 — последният 5-мин. бар, няма го в сутрешния бриф )" in txt.replace("бриф)", "бриф )") and "CRCL +4.0% ($74.96; затваряне $72.08)" in txt
b.pop("preopen")
print("  ✓ без обем при всички — „Обемът в премаркета не е наличен (Yahoo) — провери го в първите минути“; при част — „… за B …“; с обем — числото в реда, без предупреждението")

print()
print("── 6. прозорецът и задачата ──")
assert preopen.skip_reason(NOW) is None and options_record.skip_reason(NOW, None) is None                                                                                # 09:05 EST, вторник → върви
assert "след отварянето" in options_record.skip_reason(NOW + dt.timedelta(hours=1)) and "не е сесия" in options_record.skip_reason(dt.datetime(2026, 11, 7, 14, 5, tzinfo=dt.timezone.utc))
from zoneinfo import ZoneInfo
from src import sessions
d, odd, closed_ran = dt.date(2026, 10, 1), [], []
while d <= dt.date(2027, 12, 31):                                                   # и двете смени на часа (САЩ и Европа), с разминаванията им
    if d.weekday() < 5:                                                              # графикът в cron-job.org: „5 14,15 * * 1-5“ по Берлин
        runs = [pd.Timestamp(dt.datetime(d.year, d.month, d.day, h, 5, tzinfo=ZoneInfo("Europe/Berlin"))).tz_convert("UTC") for h in (14, 15)]
        ok = [r for r in runs if preopen.skip_reason(r) is None]
        if not sessions.is_session(d):
            closed_ran += [d] if ok else []
        elif len(ok) != 1 or ok[0].tz_convert("America/New_York").strftime("%H:%M") != "09:05":
            odd.append((d, [r.tz_convert("America/New_York").strftime("%H:%M") for r in runs]))
    d += dt.timedelta(days=1)
assert odd == [] and closed_ran == [], (odd[:5], closed_ran[:5])
mism = lambda day: [pd.Timestamp(dt.datetime.fromisoformat(day + f" {h}:05").replace(tzinfo=ZoneInfo("Europe/Berlin"))).tz_convert("America/New_York").strftime("%H:%M")
                    for h in (14, 15) if preopen.skip_reason(pd.Timestamp(dt.datetime.fromisoformat(day + f" {h}:05").replace(tzinfo=ZoneInfo("Europe/Berlin")))) is None]
assert mism("2026-10-27") == ["09:05"] and mism("2026-11-04") == ["09:05"] and mism("2027-03-16") == ["09:05"] and mism("2027-03-30") == ["09:05"]
assert "преди прозореца" in preopen.skip_reason(pd.Timestamp("2026-11-04 13:05", tz="UTC"))                                    # 14:05 Берлин = 08:05 EST — без второ обновяване
assert "след отварянето" in preopen.skip_reason(pd.Timestamp("2026-10-27 14:05", tz="UTC"))                                   # 15:05 Берлин = 10:05 EDT (разминаването)
import src.screener as _scr
_bu, _scr.build_universe = _scr.build_universe, lambda *a, **k: (_ for _ in ()).throw(AssertionError("извън прозореца не се тегли нищо"))
try:
    with q():
        assert preopen.main(pd.Timestamp("2026-11-04 13:05", tz="UTC").to_pydatetime()) == 0                                # 08:05 Ню Йорк → изход 0, нищо не пипа
finally:
    _scr.build_universe = _bu
assert not (config.DATA_DIR / "preopen").exists()
yml = (ROOT / ".github" / "workflows" / "options_record.yml").read_text(encoding="utf-8")
steps = yml.split("- name: ")
rec, pre, com = (next(s for s in steps if s.startswith(n)) for n in ("Record option chains", "Pre-open update", "Commit record"))
assert "python src/options_record.py" in rec and "if: always()" not in rec.split("#")[0]                                  # коментарът преди следващата стъпка — не е част от нея
assert "if: always()" in pre and "python src/preopen.py" in pre and "EDGAR_UA: ${{ secrets.EDGAR_UA }}" in pre and "EMAIL_TO: ${{ secrets.EMAIL_TO }}" in pre
assert "if: always()" in com and "git add data/preopen docs/index.html" in com and "git add data/options_daily.json" in com
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert "anthropic" not in src.lower() and "_call_claude" not in src                                                            # без AI
print("  ✓ прозорецът — същият като на записа на опциите: до края на 2027 всяка сесия — точно едно обновяване, в 09:05 Ню Йорк (и в седмиците с разминаване на смяната на часа:"
      " 27.10.2026 и 16.03.2027 — 14:05 Берлин; 04.11.2026 и 30.03.2027 — 15:05); 08:05 / 10:05 Ню Йорк и дните без сесия — пропуска, без теглене;"
      " отделна стъпка с if: always() (и commit-ът), без AI")
print("\n✅ test_preopen: всичко мина")
