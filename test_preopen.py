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
from src import preopen, render, options_record

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "preopen_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
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
assert L["filings_8k"][0]["text"] == "8-K (SEC), 02.11 16:27 ET: т. 2.02 — резултати от дейността" and L["filings_8k"][0]["items"] == ["2.02"] and L["headline"] is None
assert A["gap_pct"] == 12.48 and A["headline"]["title"] == "Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript" and A["filings_8k"][0]["text"].startswith("8-K (SEC), 02.11 16:03 ET: т. 2.02")
assert calls == [("LSCC", "2026-11-02"), ("AEIS", "2026-11-02")]
print("  ✓ LSCC +13.5% (пренебрегнат, 3 мес. −31%) — 8-K т. 2.02 в 16:27 ET; AEIS +12.5% — 8-K т. 2.02 в 16:03 ET и „Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript“; FN — под 10%")

print()
print("── 3. наблюдаваните (РЕАЛНО: ELF, CRCL под ±3% в 09:05) ──")
w = preopen.watch_gaps(pts, ["ELF", "CRCL", "LSCC"])
assert [x["ticker"] for x in w] == ["LSCC"] and w[0]["gap_pct"] == 13.51                                                  # СИНТЕТИЧНО: LSCC като наблюдаван
assert preopen.watch_gaps(pts, ["ELF", "CRCL"]) == []
print("  ✓ ELF и CRCL — под ±3%; наблюдаван с гап (LSCC, синтетично в списъка) — в реда")

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
assert "LSCC +13.5% ($108.32 в 09:00 Ню Йорк; затваряне $95.44) · пренебрегнат (3 мес. -31%) 8-K (SEC), 02.11 16:27 ET: т. 2.02 — резултати от дейността" in page
assert "„Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript“" in page
mail = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", preopen.email_html(res))))
assert mail.startswith(" Преди отварянето · 03.11, 09:05 Ню Йорк (15:05 Берлин)") and "AEIS +12.5% ($244.30; затваряне $217.19) · пренебрегнат (3 мес. -36%)" in mail
assert "„Advanced Energy (AEIS) Q3 2026 Earnings Call Transcript“ " in mail and "Transcript“ ·" not in mail                  # без празен източник
quiet = {**res, "gaps": [], "levels": [], "watch": []}
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
print("  ✓ карето най-горе (преди термометъра); имейлът — само при нещо; „Нищо за отбелязване“; провал — не изглежда като „нищо“; сутрешният бриф — без каре")

print()
print("── 6. прозорецът ──")
assert options_record.skip_reason(NOW, None) is None                                                                                # 09:05 EST, вторник → върви
assert "след отварянето" in options_record.skip_reason(NOW + dt.timedelta(hours=1)) and "не е сесия" in options_record.skip_reason(dt.datetime(2026, 11, 7, 14, 5, tzinfo=dt.timezone.utc))
src = (ROOT / "src" / "preopen.py").read_text(encoding="utf-8")
assert "anthropic" not in src.lower() and "_call_claude" not in src                                                            # без AI
print("  ✓ 09:05 Ню Йорк във вторник — върви; 10:05 / събота — пропуска; без AI")
print("\n✅ test_preopen: всичко мина")
