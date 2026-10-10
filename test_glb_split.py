"""
С2 (втори преглед, 10.10.2026) · GLB: замразената линия се мащабира при сплит след входа (както книгата на Уиш с signal_close).

До 10.10: събитието пази линията в скалата на деня на входа, а Yahoo коригира историята ретроактивно при сплит → след 2:1 close-ът е в новата скала, линията — в старата
→ close < линията × 0.97 → картата отпада; ако месецът на пробива е минал, не се връща. Сега: при входа се пази since_close; всеки ден screen() подава close-а за същата дата
от сегашните данни (close_at_since); разлика над GLB_WISH_SPLIT_TOLERANCE → line и prior_high се делят на съотношението.

РЕАЛНО: GLB картата на ADI от брифа на 05.10 (tests/fixtures/brief_2026-10-05.json: линия = prior_high $413.85, цена $417.15); дневните close-ове на MRK
(tests/fixtures/glb_prices_2026-10-05.json). СИНТЕТИЧНО: датата на входа 05.10 като "since", сплитът 2:1 (и 3:2) и цените след него.
Пускане: python test_glb_split.py
"""
import sys, json, pathlib, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import pandas as pd
import config
from src import glb_screener as g

B05 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-05.json").read_text(encoding="utf-8"))
ADI = next(c for c in B05["glb_candidates"] if c["ticker"] == "ADI")
assert ADI["prior_high"] == 413.85 and ADI["price"] == 417.15
EV = {**{k: v for k, v in ADI.items() if k not in ("price", "in_screener", "already_open_position")}, "line": ADI["prior_high"], "since": "2026-10-05", "since_bar": "2026-10-02"}


def run(events, obs, today="2026-10-20"):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        res = g.apply_hysteresis(events, obs, today)
    return res, out.getvalue()


print("── 1. КОНТРОЛ: без since_close (събитие отпреди 10.10) сплитът изхвърля картата ──")
(new, rows, ch), _ = run({"ADI": dict(EV)}, {"ADI": {"close": 209.0, "close_at_since": 208.575}})      # СИНТЕТИЧНО: 2:1 → 417.15 / 2
assert ch["dropped"] == ["ADI"] and not rows
print("  ✓ реалната ADI (линия $413.85) + СИНТЕТИЧЕН сплит 2:1 (close $209.00): без since_close картата отпада — така беше до 10.10")

print()
print("── 2. новото: since_close при входа → линията се мащабира ──")
(new, rows, ch), _ = run({}, {"ADI": {"close": 417.15, "last_date": "2026-10-02",
                               "entry": {**{k: v for k, v in ADI.items() if k not in ("in_screener", "already_open_position")}}}}, today="2026-10-05")
assert new["ADI"]["since_close"] == 417.15 and new["ADI"]["since_bar"] == "2026-10-02" and new["ADI"]["since"] == "2026-10-05" and new["ADI"]["line"] == 413.85
(new2, rows2, ch2), log = run(new, {"ADI": {"close": 209.0, "close_at_since": 208.575}})
ev = new2["ADI"]
assert ch2["dropped"] == [] and rows2 and abs(ev["line"] - 206.925) < 0.01 and ev["prior_high"] == round(413.85 / 2, 2) and ev["since_close"] == 208.575
assert ev["split_scales"] == [{"date": "2026-10-20", "scale": 2.0}] and rows2[0]["pct_vs_line"] == round((209.0 / ev["line"] - 1) * 100, 1)
assert "сплит след входа (2026-10-05)" in log
print(f"  ✓ вход на 05.10 (since_close $417.15) → на 20.10 СИНТЕТИЧЕН сплит 2:1: линията $413.85 → ${ev['line']:.3f}, картата остава (+{rows2[0]['pct_vs_line']}% над линията), записано split_scales")
(new3, rows3, ch3), log3 = run(new2, {"ADI": {"close": 210.5, "close_at_since": 208.575}}, today="2026-10-21")
assert new3["ADI"]["line"] == ev["line"] and "сплит" not in log3                                        # вече мащабирана — не се мащабира втори път
(new4, rows4, ch4), _ = run({"ADI": {**EV, "since_close": 417.15}}, {"ADI": {"close": 278.0, "close_at_since": 278.1}})   # СИНТЕТИЧНО: 3:2
assert abs(new4["ADI"]["line"] - 413.85 / (417.15 / 278.1)) < 0.01 and not ch4["dropped"]
(new5, _, _), log5 = run({"ADI": {**EV, "since_close": 417.15}}, {"ADI": {"close": 419.0, "close_at_since": 417.0}})        # 0.04% — под толеранса
assert new5["ADI"]["line"] == 413.85 and "сплит" not in log5
print("  ✓ на следващия ден не се мащабира повторно; 3:2 също; разлика под 0.5% (корекция на данните, не сплит) — без промяна")

print()
print("── 3. _close_on върху РЕАЛНИТЕ дневни close-ове на MRK (и след СИНТЕТИЧЕН сплит) ──")
FX = json.loads((ROOT / "tests" / "fixtures" / "glb_prices_2026-10-05.json").read_text(encoding="utf-8"))
mrk = FX["daily"]["MRK"]
df = pd.DataFrame({"Close": list(mrk.values())}, index=pd.to_datetime(list(mrk.keys())))
day = list(mrk)[-5]
assert g._close_on(df, day) == mrk[day] and g._close_on(df, "2026-10-04") is None and g._close_on(df, None) is None
df_tz = df.copy(); df_tz.index = df_tz.index.tz_localize("America/New_York")
assert g._close_on(df_tz, day) == mrk[day]
assert g._close_on(df / 2, day) == mrk[day] / 2
print(f"  ✓ close на MRK за {day} = ${mrk[day]} (реален); неделя → None; с часова зона в индекса — същото; след сплит 2:1 → половината")

print()
print("── 4. screen() подава close_at_since за тикърите със събитие ──")
src = (ROOT / "src" / "glb_screener.py").read_text(encoding="utf-8")
assert '"close_at_since": _close_on(df, (events.get(sym) or {}).get("since_bar"))' in src and '"last_date": _bar_date(df)' in src and "ev = _rescale_for_split(sym, ev, ob, today)" in src
print("  ✓ наблюденията носят last_date и close_at_since по ДАТАТА НА БАРА (since_bar), не по датата на брифа; apply_hysteresis мащабира преди проверката за изход")
print()
print("Всички тестове минаха.")

print()
print("── 5. текстът на картата е от текущия код, не от състоянието (РЕАЛЕН остарял текст на MRK от data/glb_state.json, 10.10) ──")
stale = "Тесен, добре удържан base преди пробива (band_hold>=85% от последните 63 дни) — по-нисък очакван volatility профил, най-близък до класически Stage 2 setup."
(new6, rows6, _), _ = run({"MRK": {"glb_type": "classic", "line": 140.0, "since": "2026-10-01", "risk_note": stale}}, {"MRK": {"close": 149.28}})
assert rows6[0]["risk_note"] == g.RISK_NOTES["classic"] != stale
(new7, rows7, _), _ = run({}, {"ZZZ": {"close": 105.0, "last_date": "2026-10-09", "entry": {"glb_type": "momentum", "prior_high": 100.0, "risk_note": stale, "price": 105.0}}})
assert "risk_note" not in new7["ZZZ"] and rows7[0]["risk_note"] == g.RISK_NOTES["momentum"]
print("  ✓ събитие със стария текст → картата показва текущия RISK_NOTES['classic']; ново събитие не замразява risk_note")
print()
print("Всички тестове минаха (вкл. т.5).")
