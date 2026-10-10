"""
С5 (втори преглед, 10.10.2026) · дневно канарче за split корекцията на Yahoo.

Коректността на нивата (pivot, стопове, GLB линия, реплеите) зависи от това как доставчикът коригира историята за сплитове; двойна корекция вече е
надувала резултат ×4 (реплеят на Уиш, 08.10). yfinance/pandas са закрепени в requirements.txt, но поведението на Yahoo може да се смени и без нова версия.
Проверка: close на NVDA за 07.06.2024 (последната сесия преди сплита 10:1 от 10.06.2024) в данни, коригирани САМО за сплитове (auto_adjust=False — както
книгите и GLB): очаквано ≈ $120.888 (= 1208.88 / 10; измерено на 10.10.2026 с yfinance 1.5.2 и 1.7.0). Двойна корекция → ≈ 12.09; липсваща → ≈ 1208.88.
Една мрежова заявка; провал на тегленето → ok None (неизвестно, без банер — паднал Yahoo се вижда от другите предупреждения).
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

EXPECTED = {"ticker": "NVDA", "date": "2024-06-07", "close": 120.888}


def check(download=None) -> dict:
    """{"ok": True/False/None, "ticker", "date", "expected", "close", "error"}; download — подменяемо в теста (yf.download)."""
    out = {"ok": None, **{k: EXPECTED[k] for k in ("ticker", "date")}, "expected": EXPECTED["close"], "close": None, "error": None}
    try:
        if download is None:
            import yfinance as yf
            download = yf.download
        df = download(EXPECTED["ticker"], start="2024-06-05", end="2024-06-12", auto_adjust=False, progress=False)
        close = df["Close"]
        if hasattr(close, "columns"):                       # yfinance ≥ 0.2.4x: колони по тикър
            close = close[EXPECTED["ticker"]] if EXPECTED["ticker"] in close.columns else close.iloc[:, 0]
        idx = [str(getattr(d, "date", lambda: d)()) for d in close.index]
        if EXPECTED["date"] not in idx:
            out["error"] = f"няма бар за {EXPECTED['date']}"
            return out
        v = float(close.iloc[idx.index(EXPECTED["date"])])
        out["close"] = round(v, 3)
        out["ok"] = abs(v / EXPECTED["close"] - 1) <= config.DATA_CANARY_TOLERANCE
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
