"""
03.11.2026 · разходката, т. 13–15: секцията GLB и книгата „GLB по Уиш“ на страницата.
  • заглавие „GLB Watchlist · Green Line Breakout“ + кратко инфо ВЕДНЪЖ (правилото на Уиш, нашата свежест 20 сесии / +10%, рискът) и ред за пазара (QQQ спрямо SMA10 / SMA20) с етикет
    „наш заместител на пазарното правило на Уиш“ — неговият GMI не е публикуван точно (проучването от 07.10);
  • Classic / Momentum: едно изречение определение → компактна таблица (Тикър · над линията · сесии · месеци без връх · обем на пробива; типът е в заглавието — прегледът от 04.11), подредена по обема на пробива, без филтър;
    ред → клик → цялата карта; под нея сгънато „▸ Отворени в книгата — Classic (N)“;
  • книгата: един видим ред (записи · затворени (exec) · отворени (exec) · статистика от 20 записа), „▸ Как се мери“, „▸ Всички записи (N)“ — с колона „Обем на пробива“, доходността само exec;
  • архивът (по close) — ред + сгънати записи, докато има отворени.

РЕАЛНО: tests/fixtures/brief_2026-10-19.json (рамката); tests/fixtures/glb_book_2026-11-03.json.gz (записите на книгата към 03.11, баровете, картите от 03.11).
СИНТЕТИЧНО (означено): картите в т. 1 са построени от РЕАЛНИТЕ полета на картите от 03.11 (тикър, тип, обем, сесии, % над линията, месеци); QQQ в т. 3; yf.download в т. 2 връща РЕАЛНИТЕ барове.
Пускане: python test_glb_layout.py
"""
import sys, json, gzip, copy, pathlib, tempfile, io, contextlib, re, datetime as dt, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_glblayout_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import backtest, render

FX = json.loads(gzip.decompress((ROOT / "tests" / "fixtures" / "glb_book_2026-11-03.json.gz").read_bytes()).decode("utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())
flat = lambda h: re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", h)))

# книгата към 03.11 — след попълването на обема и exec (както в test_glb_book_volume)
BARS = {s: pd.DataFrame({"Open": b["o"], "High": b["h"], "Low": b["l"], "Close": b["c"], "Volume": b["v"]}, index=pd.to_datetime(b["d"])) for s, b in FX["bars"].items()}
frame = pd.concat({f: pd.DataFrame({t: BARS[t][f] for t in sorted(BARS)}) for f in ("Open", "High", "Low", "Close", "Volume")}, axis=1)
tracker = copy.deepcopy(FX["records"])
real_dl, real_load = backtest.yf.download, backtest._load_tracker
backtest.yf.download = lambda tickers, **k: frame[[c for c in frame.columns if c[1] in tickers]]
backtest._load_tracker = lambda: tracker
try:
    with q():
        backtest._resolve_open_positions(tracker, today=dt.date(2026, 11, 3))
        GWH = backtest.get_glb_wish_summary(backtest.CATEGORY_GLB_WISH_HIGH)
finally:
    backtest.yf.download, backtest._load_tracker = real_dl, real_load

CARDS = []
for t, c in FX["cards"].items():                                                                      # СИНТЕТИЧНО: картите — от РЕАЛНИТЕ полета на 03.11
    CARDS.append({"ticker": t, "rule": "wish_high", "glb_type": c["glb_type"], "line": 100.0, "prior_high": 100.0, "prior_high_month": "2026-01", "months_unpenetrated": c["months_unpenetrated"],
                  "since": c["since_bar"], "since_bar": c["since_bar"], "sessions": c["sessions"], "max_sessions": 20, "price": 100.0 * (1 + c["pct_vs_line"] / 100), "pct_vs_line": c["pct_vs_line"],
                  "breakout_volume_ratio": c["breakout_volume_ratio"], "x_from_52w_low": 1.5, "ath_label": "all_time_high", "risk_note": "НЕ_БИВА_ДА_СЕ_ВИЖДА " + c["glb_type"], "company": t})


def page_of(**over):
    b = copy.deepcopy(B19)
    for k, v in over.items():
        if k == "backtest":
            b.setdefault("backtest", {}).update(v)
        else:
            b[k] = v
    with q():
        return render.render_dashboard(b, publish=False)


print("── 1. групите: по обема на пробива, без филтър; отворените записи — по тип ──")
G = render.glb_groups(CARDS, GWH)
assert [c["ticker"] for c in G["classic"]["cards"]] == ["NDAQ", "EHC", "EBAY", "ED", "MA", "AFG", "GILD", "BRK-B", "XOM"]   # 2.42 · 2.34 · 1.69 · 1.46 · 1.34 · 1.26 · 1.06 · 1.02 · 0.98
assert [c["ticker"] for c in G["momentum"]["cards"]] == ["CART", "QLYS", "MAR", "ALLE"]                                  # 4.38 · 1.81 · 1.75 · 1.2
assert len(G["classic"]["open"]) == 6 and {r["ticker"] for r in G["momentum"]["open"]} == {"CART", "ALLE", "MAR"} and G["insufficient"]["open"] == []
assert render.glb_groups([{**CARDS[0], "breakout_volume_ratio": None}] + CARDS[1:], None)["classic"]["cards"][-1]["breakout_volume_ratio"] is None     # без обем — накрая
assert render.glb_groups(CARDS, None)["classic"]["open"] is None                                                        # без книгата — без реда „Отворени в книгата“
old = render.glb_groups(CARDS, {"enabled": True, "live": [{"ticker": "X", "glb_type": "classic"}, {"ticker": "Y", "glb_type": None}]})   # стар бриф: само "live"
assert [r["ticker"] for r in old["classic"]["open"]] == ["X"] and [r["ticker"] for r in old["insufficient"]["open"]] == ["Y"]
print("  ✓ 13-те карти от 03.11 — Classic: NDAQ 2.42× → XOM 0.98×; Momentum: CART 4.38× → ALLE 1.2×; отворените в книгата — Classic 6, Momentum 3 (CART, ALLE, MAR); стар бриф — по glb_type от „live“")

print()
print("── 2. страницата: инфо веднъж, таблиците, отворените под своя списък ──")
p = page_of(glb_candidates=CARDS, backtest={"glb_wish_high": GWH, "glb_wish": {}})
sec = p[p.index("GLB Watchlist · Green Line Breakout"):]
sec = sec[:sec.index("</section>")]
fs = flat(sec)
assert fs.count("Правилото е на Eric Wish") == 1 and "картата се вижда до 20-ата сесия от пробива и докато цената е до +10% над линията" in fs and fs.count("Рискът:") == 1
assert "НЕ_БИВА_ДА_СЕ_ВИЖДА" not in sec                                                                                 # бележката за риска — не на всяка карта
assert "Тикър Над линията Сесии Месеци без връх Обем на пробива" in fs and "Обем на пробива Тип" not in fs         # 04.11: без колоната „Тип“ — повтаря заглавието
row = lambda t: fs.index(f"{t} {FX['cards'][t]['pct_vs_line']:+.1f}% ")
assert row("NDAQ") < row("EHC") < row("EBAY") < row("XOM") and row("CART") < row("QLYS") < row("ALLE")
assert "EHC +7.2% 3 от 20 11 м 2.3×" in fs                                                                    # ред: тикър · над линията · сесии · месеци · обем · тип
i_c, i_oc, i_m, i_om = fs.index("Classic GLB (9)"), fs.index("Отворени в книгата — Classic (6)"), fs.index("Momentum GLB (4)"), fs.index("Отворени в книгата — Momentum (3)")
assert i_c < i_oc < i_m < i_om                                                                                          # отворените — под своя списък, не накрая
assert sec.count('<details class="wt-item">') == 13 and sec.count('<div class="glb-card') == 13                          # ред → клик → цялата карта
cl = copy.deepcopy(CARDS); [c.update(ath_label="new_high_since_listing", in_screener=True) for c in cl if c["ticker"] == "AFG"]                # СИНТЕТИЧНО: кратка история и наш скрийнър при AFG
fl = flat(page_of(glb_candidates=cl, backtest={"glb_wish_high": GWH, "glb_wish": {}}))
assert "AFG ✓ скрийнър +1.9% 3 от 20 53 м · от листването 1.3×" in fl and fl.count("· от листването") == 1
print("  ✓ инфото — веднъж; рискът не е на всяка карта; Classic GLB (9) → ▸ Отворени в книгата — Classic (6) → Momentum GLB (4) → ▸ … Momentum (3); ред → клик → карта")

print()
print("── 3. редът за пазара (СИНТЕТИЧНО: QQQ) ──")
mk = {"date": "2026-11-02", "close": 681.09, "sma10": 709.77, "sma20": 724.43, "above10": False, "above20": False}
fp = flat(page_of(glb_candidates=CARDS, qm_market=mk))
g = fp[fp.index("GLB Watchlist"):]
assert "Nasdaq под 10/20 DMA · QQQ $681.09 на 02.11, SMA10 $709.77, SMA20 $724.43 — наш заместител на пазарното правило на Уиш" in g and "Kullamägi не би търгувал" not in g[:900]
assert render.glb_market_line({**mk, "above20": True}) == "Nasdaq над 20 DMA, под 10 DMA" and render.glb_market_line(None) is None
assert "наш заместител на пазарното правило на Уиш" not in flat(page_of(glb_candidates=CARDS))[fp.index("GLB Watchlist"):]     # без QQQ — без реда
print("  ✓ „Nasdaq под 10/20 DMA · QQQ … — наш заместител на пазарното правило на Уиш (неговият индикатор GMI …)“; без данни — без реда")

print()
print("── 4. книгата: един ред, „Как се мери“, всички записи с обема; доходността — exec ──")
i = p.index(f"{config.GLB_WISH_BOOK_NAME} · книга (измерване, не препоръка)")
bk = p[i:p.index("</section>", i)]
fb = flat(bk)
line = fb[:fb.index("Как се мери")]
cg, og = GWH["closed_group"], GWH["open_group"]
assert f"11 записа · затворени 2 ({cg['avg_return_pct_exec']:+.1f}%) · отворени 9 ({og['avg_return_pct_exec']:+.1f}%) · статистика от 20 записа (сега 11)" in line
assert "-3.1%" not in line and cg["avg_return_pct"] == -3.09                                                            # literal — само в данните
assert "Всички записи (11)" in fb and "Обем на пробива" in fb and "CART" in fb and "4.4×" in fb and bk.count('<tr><td class="mono">') == 11
assert "Последно затворени" not in fb and "Отворени и чакащи" not in fb and "literal" not in line
assert "<summary>Как се мери</summary>" in bk and "<summary>Всички записи (11)</summary>" in bk
print(f"  ✓ „11 записа · затворени 2 ({cg['avg_return_pct_exec']:+.1f}%) · отворени 9 ({og['avg_return_pct_exec']:+.1f}%) · статистика от 20 записа (сега 11)“; ▸ Как се мери; ▸ Всички записи (11) с колона „Обем на пробива“")
print("\n✅ test_glb_layout: всичко мина")
