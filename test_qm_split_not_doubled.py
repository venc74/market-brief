"""
Qullamaggie скенер · цените и обемът не се коригират втори път за сплитове (09.10.2026). Yahoo Close/Open/High/Low И Volume при yf.download(..., auto_adjust=False) са ВЕЧЕ ретроактивно split-коригирани;
старата qm_breakout.split_adjust (цените ÷ коефициента, обемът × коефициента) ги коригираше втори път и акции със сплит или корекция от отделяне изглеждаха като лидери по ръст → фалшиви кандидати.
Корекцията е махната от fetch_frames (и actions=True).

РЕАЛНО: tests/fixtures/qm_split_false_candidates_2026-10-08.json — барове (до датата на доказателството) на CVNA (5:1 на 08.05.2026), MLI (2:1 на 01.07.2026) и MIDD (корекция 1.243 на 07.07.2026) точно както ги
връща Yahoo (yfinance 1.5.2, 08.10.2026), с реалната колона "Stock Splits"; "lead" = перцентилът на ръста в ЦЕЛИЯ универс от 893 тикъра към тази дата, веднъж при двойното деление и веднъж без него (смятан извън репото
върху целия универс). tests/fixtures/yahoo_splits_2026-10-08.json — реалните отговори за NVDA, AAPL и AMZN (за обема). СИНТЕТИЧНО (маркирано): подменените yf.download; "старият код" е точно копие на махнатата функция.
Пускане: python test_qm_split_not_doubled.py
"""
import sys, json, pathlib, statistics, datetime as dt
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import pandas as pd
import config
from src import qm_breakout as q

FX = json.loads((ROOT / "tests" / "fixtures" / "qm_split_false_candidates_2026-10-08.json").read_text(encoding="utf-8"))
SP = json.loads((ROOT / "tests" / "fixtures" / "yahoo_splits_2026-10-08.json").read_text(encoding="utf-8"))["tickers"]
EV = {e["ticker"]: e for e in FX["evidence"]}
assert sorted(EV) == ["CVNA", "MIDD", "MLI"]


def bars(t):
    d = FX["tickers"][t]
    return pd.DataFrame({"Open": d["o"], "High": d["h"], "Low": d["l"], "Close": d["c"], "Volume": d["v"]}, index=pd.to_datetime(d["dates"]))


def old_split_adjust(df):                                                  # ТОЧНО КОПИЕ на махнатата qm_breakout.split_adjust (само за сравнение)
    sp = df["Stock Splits"]
    sp = sp[(sp != 0) & sp.notna()]
    if sp.empty:
        return df
    df = df.copy()
    for d, ratio in sp.items():
        if not ratio or ratio == 1:
            continue
        m = df.index < d
        for k in ("Open", "High", "Low", "Close"):
            df.loc[m, k] = df.loc[m, k] / ratio
        df.loc[m, "Volume"] = df.loc[m, "Volume"] * ratio
    return df


print("── 1. предпоставките върху РЕАЛНИТЕ отговори на Yahoo ──")
for t, d in FX["tickers"].items():
    (sd, ratio), = d["splits"].items()
    k = d["dates"].index(sd)
    ch = d["c"][k] / d["c"][k - 1] - 1
    assert abs(ch) < 0.12, (t, ch)
    print(f"  ✓ {t}: «Stock Splits» {ratio:g} на {sd}; close {d['c'][k - 1]:.2f} → {d['c'][k]:.2f} ({ch * 100:+.1f}%) — цените са вече непрекъснати през сплита")
for t, d in SP.items():
    k = d["dates"].index(d["split_date"]); r = list(d["splits"].values())[0]
    pre, post = statistics.median(d["v"][k - 20:k]), statistics.median(d["v"][k:k + 20])
    assert post / pre < r / 2, (t, pre, post)
    print(f"  ✓ {t}: медианният обем 20 дни преди/след сплита {pre:,.0f} → {post:,.0f} (×{post / pre:.2f}, коефициент {r:g}) — и обемът е вече коригиран")

print()
print("── 2. фалшивите кандидати: двойното деление ги създава, без него ги няма ──")
EXPECT = {"CVNA": (71.93, 5.83, 652, 45, 0.33, 280, -24), "MLI": (60.01, 3.54, 107, 12, 0.50, 80, -10), "MIDD": (138.93, 3.02, 65, 21, 0.88, 36, 9)}
for t, (lvl, adr, run, base, dist, r126_old, r126_new) in EXPECT.items():
    e = EV[t]
    raw = bars(t)
    raw_actions = raw.assign(**{"Stock Splits": [FX["tickers"][t]["splits"].get(x, 0.0) for x in FX["tickers"][t]["dates"]]})
    old = old_split_adjust(raw_actions)[["Open", "High", "Low", "Close", "Volume"]]
    rows_old, _ = q.scan_frames({t: old}, lead={t: e["lead_double"]})
    assert [r["ticker"] for r in rows_old] == [t], (t, rows_old)
    r = rows_old[0]
    assert abs(r["trigger"] - lvl) < 0.01 and abs(r["adr"] - adr) < 0.01 and round(r["runup_pct"]) == run and r["base_days"] == base and abs(r["pct_to_trigger"] / r["adr"] - dist) < 0.01, (t, r)
    # новият път: РЕАЛНИЯТ отговор на Yahoo през fetch_frames (подменено теглене)
    kw_seen = []
    def fake_download(batch, **kw):
        kw_seen.append(kw)
        return pd.concat({batch[0]: raw_actions if kw.get("actions") else raw}, axis=1)           # както Yahoo: колоната "Stock Splits" само при actions=True
    q.yf = type("Y", (), {"download": staticmethod(fake_download)})
    fr, st = q.fetch_frames([t], batch_size=1, now_utc=dt.datetime(2026, 10, 9, 5, 30, tzinfo=dt.timezone.utc))
    assert st["batches_failed"] == 0 and list(fr) == [t] and "actions" not in kw_seen[0] and kw_seen[0]["auto_adjust"] is False
    new = fr[t]
    assert list(new["Close"]) == list(raw["Close"]) and list(new["Volume"]) == list(raw["Volume"]) and list(new["Open"]) == list(raw["Open"])
    rows_new, _ = q.scan_frames({t: new}, lead={t: e["lead_correct"]})
    assert rows_new == [], (t, rows_new)
    c_old, c_new = old["Close"].to_numpy(), new["Close"].to_numpy()
    g_old, g_new = round(100 * (c_old[-1] / c_old[-127] - 1)), round(100 * (c_new[-1] / c_new[-127] - 1))
    assert (g_old, g_new) == (r126_old, r126_new), (t, g_old, g_new)
    print(f"  ✓ {t} на {e['date']}: при двойното деление 126-дневен ръст {g_old:+d}% (реално {g_new:+d}%), перцентил {e['lead_double']:.3f} (реално {e['lead_correct']:.3f}) → фалшив кандидат: ниво ${r['trigger']:.2f}, ADR {r['adr']:.2f}%, «ръст» +{r['runup_pct']:.0f}%, "
          f"база {r['base_days']} сесии, {r['pct_to_trigger'] / r['adr']:.2f} ADR до нивото; през fetch_frames без деление — няма кандидат")

print()
print("── 3. кодът ──")
import inspect
assert not hasattr(q, "split_adjust") and "actions=True" not in inspect.getsource(q.fetch_frames) and "split_adjust" not in inspect.getsource(q.fetch_frames)
print("  ✓ split_adjust е махната, fetch_frames не иска actions=True и не вика корекция; auto_adjust=False остава (без корекция за дивиденти)")
print("\n✅ test_qm_split_not_doubled: всичко мина")
