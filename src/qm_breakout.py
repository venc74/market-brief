"""
Qullamaggie Breakout скенер (06.10.2026) — отделна стратегия, ИЗЦЯЛО МЕХАНИЧЕН (нула AI), независим от CANSLIM/Weinstein и от GLB (собствено теглене на дневни данни,
същият универс като скрийнъра: S&P500 + NDX100 + MidCap400, без малки акции). Не е препоръка — измерване (виж Track Record книгата "qm_breakout").

Правилата му (преразказани; първоизточници: https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/ и https://qullamaggie.com/faq/):
  1. Лидери: най-добрите ~1–2% по ръст за 1, 3 и 6 месеца (тук: горните config.QM_LEAD_PCT-перцентилни 10% от нашия универс от ~900, защото 1–2% от ~7000 са 70–140 акции);
  2. голям ръст в последните 1–3 месеца (негово: 30–100%+; тук ≥ config.QM_RUN_MIN, "отпуснатата" конфигурация на реплея);
  3. организирана консолидация ≈ 2 седмици – 2 месеца с higher lows и стягащ се диапазон; цената "сърфира" по растящите 10- и 20-дневна MA; спадащ обем в базата;
  4. пробив с разширение на диапазона — НИВОТО на пробива тук е най-високият High на последните 10 сесии (върхът на флага);
  5. ADR (средното H/L − 1 за 20 сесии, формулата от FAQ) ≥ config.QM_ADR_MIN; стопът (low of the day) не бива да е по-широк от ADR.
Какво НЕ се изчислява от дневните данни и остава на потребителя: входът по върха на отварящия диапазон (1/5/60 минути) и стопът low of the day — брифът дава нивата, не самия вход.

Резултатът на реплея (02.2024–10.2026, 904 тикъра, дневни приближения): няма демонстрирана алфа — виж CLAUDE.md и DESIGN.md на проучването.
Чисти функции (compute_features / check_candidate / scan_frames) + мрежа само във fetch_frames. Graceful: провал на партида/тикър се пропуска и се брои в diag.
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

try:
    import yfinance as yf
except Exception:                                    # pragma: no cover
    yf = None

NOTE_BG = ("Входът е по opening range high в сесията, стопът — low of day; брифът дава нивата, не самия вход. "
           "Отделна стратегия — измерване, не препоръка.")
RANK_BARS = (21, 63, 126)                            # 1, 3 и 6 месеца в търговски дни
MIN_BARS = 130                                       # история за ръста за 6 месеца и за признаците


def params() -> dict:
    return dict(LEAD=config.QM_LEAD_PCT, ADR_MIN=config.QM_ADR_MIN, DV_MIN=config.QM_DOLLAR_VOLUME_MIN, PRICE_MIN=config.QM_PRICE_MIN, RUN_MIN=config.QM_RUN_MIN,
                RUN_LB=config.QM_RUN_LOOKBACK_BARS, PEAK_W=config.QM_PEAK_WINDOW_BARS, BASE_MIN=config.QM_BASE_MIN_BARS, BASE_MAX=config.QM_BASE_MAX_BARS,
                DEPTH_MAX=config.QM_DEPTH_MAX, HL_TOL=config.QM_HIGHER_LOW_TOL, TIGHT=config.QM_TIGHT_MAX, VOL_DRY=config.QM_VOL_DRY, NEAR_ADR=config.QM_NEAR_ADR,
                TRIG_N=config.QM_TRIGGER_BARS)


def compute_features(df: pd.DataFrame) -> dict:
    """Масиви за един тикър от дневни Open/High/Low/Close/Volume (индекс = дата, без NaN)."""
    o, h, l, c, v = (df[k].to_numpy(dtype=float) for k in ("Open", "High", "Low", "Close", "Volume"))
    cs, hs, ls, vs = pd.Series(c), pd.Series(h), pd.Series(l), pd.Series(v)
    return {
        "idx": df.index, "o": o, "h": h, "l": l, "c": c, "v": v, "n": len(df),
        "adr": (100 * ((hs / ls).rolling(20).mean() - 1)).to_numpy(),                 # ADR20 в % (формулата от qullamaggie.com/faq)
        "s10": cs.rolling(10).mean().to_numpy(), "s20": cs.rolling(20).mean().to_numpy(),
        "v5": vs.rolling(5).mean().to_numpy(), "v50": vs.rolling(50).mean().to_numpy(),
        "dv20": (cs * vs).rolling(20).mean().to_numpy(),
    }


def check_candidate(f: dict, i: int, lead: float, P: dict | None = None) -> dict | None:
    """
    Кандидат ли е тикърът за пробив на следващата сесия, като сигналният бар е i (последният завършен)? Връща речник с числата на картата или None.
    Не гледа бара след i (без заглеждане напред) — ползва се и от реплея върху историята.
    """
    P = P or params()
    if i < MIN_BARS or i >= f["n"]:
        return None
    a, c = f["adr"][i], f["c"][i]
    if not (a == a and a >= P["ADR_MIN"]) or c < P["PRICE_MIN"] or not (f["dv20"][i] >= P["DV_MIN"]):
        return None
    if not (lead == lead and lead >= P["LEAD"]):                                           # лидер по ръст за 1/3/6 месеца
        return None
    s10, s20 = f["s10"][i], f["s20"][i]
    if not (s10 > f["s10"][i - 5] and f["s20"][i] > f["s20"][i - 5] and s10 > s20):      # растящи 10 и 20 MA
        return None
    if not (c >= s20 and c >= 0.98 * s10 and c <= s10 * (1 + 0.75 * a / 100)):             # цената "сърфира" около MA
        return None
    h, l = f["h"], f["l"]
    w0 = i - P["PEAK_W"]
    p = w0 + int(np.argmax(h[w0:i + 1]))
    base = i - p
    if not (P["BASE_MIN"] <= base <= P["BASE_MAX"]):                                       # консолидация ≈ 2 седмици – 2 месеца
        return None
    low_before = l[max(0, p - P["RUN_LB"]):p + 1].min()
    runup = h[p] / low_before - 1
    if not runup >= P["RUN_MIN"]:                                                           # голям ръст преди базата
        return None
    depth = 1 - l[p + 1:i + 1].min() / h[p]
    if not (depth <= P["DEPTH_MAX"] and c >= h[p] * (1 - P["DEPTH_MAX"])):                  # организиран пулбек
        return None
    m2, m1 = l[i - 4:i + 1].min(), l[i - 9:i - 4].min()
    if not m2 >= m1 * (1 - P["HL_TOL"]):                                                    # higher lows (последните 5 vs предишните 5)
        return None
    if base >= 15 and not m1 >= l[i - 14:i - 9].min() * (1 - P["HL_TOL"]):
        return None
    rng5 = float(np.mean(h[i - 4:i + 1] / l[i - 4:i + 1] - 1))
    tight = rng5 / (a / 100)                                                                # среден дневен диапазон на последните 5 бара спрямо ADR (по-малко = по-стегнато)
    if not tight <= P["TIGHT"]:
        return None
    vol_ratio = f["v5"][i] / f["v50"][i]
    if not (vol_ratio <= P["VOL_DRY"]):                                                     # спадащ обем в базата
        return None
    trig = float(h[i - P["TRIG_N"] + 1:i + 1].max())
    if not (trig / c - 1 <= P["NEAR_ADR"] * a / 100):                                       # близо до нивото на пробива
        return None
    return {"close": float(c), "trigger": trig, "adr": float(a), "runup_pct": float(runup * 100), "peak": float(h[p]), "base_days": int(base),
            "depth_pct": float(depth * 100), "tight": float(tight), "vol_ratio": float(vol_ratio), "lead": float(lead),
            "vs_sma10_pct": float((c / s10 - 1) * 100), "vs_sma20_pct": float((c / s20 - 1) * 100),
            "pct_to_trigger": float((trig / c - 1) * 100), "signal_date": pd.Timestamp(f["idx"][i]).date().isoformat()}


def lead_percentiles(frames: dict[str, pd.DataFrame]) -> dict[str, float]:
    """За всеки тикър — най-добрият перцентил (0–1) в универса по ръст за 1, 3 и 6 месеца към ПОСЛЕДНИЯ бар на тикъра."""
    rets = {k: {} for k in RANK_BARS}
    for t, df in frames.items():
        c = df["Close"].to_numpy(dtype=float)
        for k in RANK_BARS:
            if len(c) > k and c[-1 - k] > 0:
                rets[k][t] = c[-1] / c[-1 - k] - 1
    ranks = {k: pd.Series(rets[k]).rank(pct=True) for k in RANK_BARS}
    out = {}
    for t in frames:
        vals = [ranks[k][t] for k in RANK_BARS if t in ranks[k].index]
        if vals:
            out[t] = float(max(vals))
    return out


def card_levels(row: dict) -> dict:
    """Нивата на картата от числата на кандидата: очакван стоп (медиана ~0.55×ADR под входа), максимален стоп (1×ADR) и размер при половин риск. Чиста функция."""
    trig, a = row["trigger"], row["adr"]
    exp_stop = trig * (1 - config.QM_EXPECTED_STOP_ADR * a / 100)
    max_stop = trig * (1 - config.QM_MAX_STOP_ADR * a / 100)
    risk_usd = config.PORTFOLIO_SIZE * config.RISK_PER_TRADE_PCT / 100 * config.QM_RISK_FACTOR
    per_share = trig - exp_stop
    cap_shares = int(config.PORTFOLIO_SIZE * config.QM_MAX_POSITION_PCT / 100 // trig)
    shares = min(int(risk_usd // per_share) if per_share > 0 else 0, cap_shares)
    per_share_max = trig - max_stop
    return {"expected_stop": round(exp_stop, 2), "expected_risk_pct": round(config.QM_EXPECTED_STOP_ADR * a, 1),
            "max_stop": round(max_stop, 2), "max_risk_pct": round(config.QM_MAX_STOP_ADR * a, 1),
            "risk_usd": round(risk_usd, 0), "shares": shares, "total_investment": round(shares * trig, 0),
            "pct_of_portfolio": round(shares * trig / config.PORTFOLIO_SIZE * 100, 1), "capped_by_position_limit": bool(shares == cap_shares and shares > 0 and
                                                                                                                 int(risk_usd // per_share) > cap_shares),
            "shares_at_max_stop": min(int(risk_usd // per_share_max) if per_share_max > 0 else 0, cap_shares)}


def scan_frames(frames: dict[str, pd.DataFrame], lead: dict[str, float] | None = None) -> tuple[list[dict], dict]:
    """
    Всички кандидати за пробив към ПОСЛЕДНИЯ бар на кадрите, подредени по стягане на базата (най-стегнатите първи). frames: {тикър: дневен DataFrame};
    lead: по подразбиране се смята от кадрите (lead_percentiles). Връща (редове, diag). Редовете носят нивата на картата (card_levels), без име на компания.
    """
    P = params()
    lead = lead if lead is not None else lead_percentiles(frames)
    rows, with_hist, leaders = [], 0, 0
    for t, df in frames.items():
        if len(df) < MIN_BARS:
            continue
        with_hist += 1
        L = lead.get(t, float("nan"))
        leaders += int(L == L and L >= P["LEAD"])
        f = compute_features(df)
        r = check_candidate(f, f["n"] - 1, L, P)
        if r:
            rows.append({"ticker": t, **r, **card_levels(r), "note": NOTE_BG})
    rows.sort(key=lambda r: (r["tight"], -r["lead"], r["ticker"]))
    as_of = max((df.index[-1] for df in frames.values() if len(df)), default=None)
    return rows, {"universe": len(frames), "with_history": with_hist, "leaders": leaders, "candidates": len(rows), "shown": min(len(rows), config.QM_MAX_CARDS),
                  "as_of": pd.Timestamp(as_of).date().isoformat() if as_of is not None else None, "lead_pct": config.QM_LEAD_PCT}


# ──────────────────────────────────────────────────────────────────────────
# Мрежа: собствено теглене на дневни данни (като GLB; не зависи от скрийнъра)
# ──────────────────────────────────────────────────────────────────────────
def split_adjust(df: pd.DataFrame) -> pd.DataFrame:
    """Само split корекция върху суровите OHLCV (цените преди сплита ÷ коефициента, обемът × коефициента); цените НЕ са коригирани за дивиденти — нивото на пробива е реалната котировка."""
    if "Stock Splits" not in df.columns:
        return df
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


def drop_incomplete(df: pd.DataFrame, now_utc: dt.datetime | None = None) -> pd.DataFrame:
    """Маха последния ред, ако е днешната (още незавършена) сесия в Ню Йорк — брифът е преди отварянето, но при ръчно пускане по време на сесия барът е частичен."""
    if df.empty:
        return df
    from zoneinfo import ZoneInfo
    ny = (now_utc or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    last = pd.Timestamp(df.index[-1]).date()
    if last == ny.date() and (ny.hour, ny.minute) < (16, 15):
        return df.iloc[:-1]
    return df


def fetch_frames(universe: list[str], batch_size: int = 100, now_utc: dt.datetime | None = None) -> tuple[dict[str, pd.DataFrame], dict]:
    """Дневни данни за ~1 година за целия универс, на партиди. Връща (кадри, {batches, batches_failed})."""
    frames: dict[str, pd.DataFrame] = {}
    st = {"batches": 0, "batches_failed": 0}
    if yf is None:
        return frames, st
    for i in range(0, len(universe), batch_size):
        batch = universe[i:i + batch_size]
        st["batches"] += 1
        try:
            data = yf.download(batch, period="1y", progress=False, auto_adjust=False, actions=True, group_by="ticker", threads=True)
            if data is None or data.empty:
                raise ValueError("празен резултат")
        except Exception as e:
            st["batches_failed"] += 1
            print(f"[qm_breakout] партида {i // batch_size + 1} не се изтегли: {type(e).__name__}: {e}")
            continue
        for sym in batch:
            try:
                df = (data[sym] if isinstance(data.columns, pd.MultiIndex) else data).dropna(subset=["Close", "High", "Low"])      # един тикър в партида → понякога плоски колони
                df = drop_incomplete(split_adjust(df), now_utc)
                if len(df) >= MIN_BARS:
                    frames[sym] = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except Exception:
                continue
    return frames, st


def scan(universe: list[str] | None = None, now_utc: dt.datetime | None = None) -> tuple[list[dict], dict]:
    """Целият скан: универс → дневни данни → кандидати (всички, подредени по стягане). Graceful: провал → ([], diag с причина)."""
    try:
        if universe is None:
            from src.screener import build_universe
            universe = build_universe()
        frames, st = fetch_frames(universe, now_utc=now_utc)
        rows, diag = scan_frames(frames)
        diag.update(st, universe=len(universe))
        diag["ok"] = bool(frames) and st["batches_failed"] < max(1, st["batches"])
        print(f"[qm_breakout] универс {len(universe)}, с история {diag['with_history']}, лидери {diag['leaders']}, кандидати {diag['candidates']} "
              f"(показват се {diag['shown']}), към {diag['as_of']}, неуспешни партиди {st['batches_failed']}/{st['batches']}")
        return rows, diag
    except Exception as e:
        print(f"[qm_breakout] скенерът пропадна: {type(e).__name__}: {e}")
        return [], {"ok": False, "error": f"{type(e).__name__}: {e}", "candidates": 0, "shown": 0}


def qm_marker(row: dict) -> dict:
    """Маркерът QM✓ (за нашите CANSLIM карти и позиции): тикърът е и кандидат за пробив на Qullamaggie. Текст при hover/клик — числата и честен надпис за стратегията."""
    return {"tag": "QM✓", "title": (f"Breakout кандидат (Qullamaggie): ниво ${row['trigger']:.2f} (+{row['pct_to_trigger']:.1f}% над затварянето), ADR {row['adr']:.1f}%, "
                                    f"ръст +{row['runup_pct']:.0f}% преди базата, база {row['base_days']} сесии, очакван стоп ≈ ${row['expected_stop']:.2f}, максимален ${row['max_stop']:.2f}.\n"
                                    f"Отделна стратегия — измерване, не препоръка. Входът е по opening range high в сесията, стопът — low of day.")}


def cards(rows: list[dict], name_lookup=None) -> list[dict]:
    """Най-много config.QM_MAX_CARDS реда (вече подредени по стягане) с име на компания (по желание, graceful)."""
    out = []
    for r in rows[:config.QM_MAX_CARDS]:
        name = r["ticker"]
        if name_lookup:
            try:
                name = name_lookup(r["ticker"]) or r["ticker"]
            except Exception:
                pass
        out.append({**r, "company": name})
    return out
