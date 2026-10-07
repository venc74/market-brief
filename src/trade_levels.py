"""
Ниво на вход, стоп и предупреждения към всяко предложение за покупка (07.10.2026, "стоп и размер"). ЧИСТ код — без мрежа, без AI, без лични числа.

Тук се смята само онова, което е еднакво за всички зрители. РАЗМЕРЪТ на позицията (брой акции, сума, загуба при стоп) НЕ се смята и НЕ се публикува — той е в браузъра
на читателя (templates/sizing_core.js), от неговия баланс и риск, които стоят само в localStorage на устройството му. Брифът е публичен: никъде в данните няма размер на
сметка, брой акции или лични числа (пази го test_no_account_numbers.py).

Две стратегии, две дефиниции на стопа:
  • CANSLIM (Action и Watchlist с buy-stop): СЪЩЕСТВУВАЩИЯТ структурен стоп — най-ниският Low на последните STOP_STRUCT_LOOKBACK_BARS бара −STOP_STRUCT_BUFFER_PCT%, най-много STOP_MAX_PCT%
    под входа (setup_rules.stop_levels през sizing.position_plan_v2). Същият, който ползва Track Record — нивата тук се ЧЕТАТ от плана, не се смятат втори път, затова не могат да се разминат.
    Записва се кое ниво е избрано: "structural" (15-баровият low) или "cap" (таванът 8%). Предупреждение: stop_pct < 0.5 × ADR → стопът е в нормалния дневен шум.
  • Kullamägi (qm_breakout и qm_ep): стоп за оразмеряване = вход × (1 − ADR) (макс. 1×ADR) — ориентировъчен, реалният стоп е дъното на деня на влизане; очакван стоп (0.55×ADR) е втори ред.
    Track Record-ът на qm_breakout НЕ ползва нито едното: там R се смята от Low-а на входния ден (trade_sim.simulate_qm) и тук нищо не го променя.

ADR% = 100 × (средно от high/low за последните 20 бара − 1) — формулата от qullamaggie.com/faq, същата като в qm_breakout и qm_ep (виж test_trade_levels.py).
"""
from __future__ import annotations

import math

import numpy as np

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

ADR_BARS = 20
NOISE_FRACTION = 0.5                                   # стоп под 0.5 × ADR е в дневния шум (само CANSLIM)
STOP_NOTE_KMG = "ориентировъчен — реалният стоп е дъното на деня на влизане"


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def adr_pct(high, low, n: int = ADR_BARS) -> float | None:
    """ADR% за последните n бара: 100 × (средно(high/low) − 1). None при по-малко от n бара, NaN/нули или low <= 0 (не гадаем)."""
    try:
        h = np.asarray(high, dtype=float)[-n:]
        l = np.asarray(low, dtype=float)[-n:]
        if len(h) < n or len(l) < n or not (np.isfinite(h).all() and np.isfinite(l).all()) or (l <= 0).any():
            return None
        return round(float(100 * (np.mean(h / l) - 1)), 2)
    except Exception:
        return None


def noise_warning(stop_pct, adr) -> str | None:
    """CANSLIM: стопът е по-близо от 0.5 × ADR до входа → "в нормалния дневен шум" (ще се удря от обикновено движение)."""
    if _ok(stop_pct) and _ok(adr) and adr > 0 and stop_pct < NOISE_FRACTION * adr:
        return f"стопът е в нормалния дневен шум (−{stop_pct:.1f}% при ADR {adr:.1f}%)"
    return None


def canslim_levels(plan: dict | None, adr, regime_factor, entry_label: str) -> dict | None:
    """
    Нивата от ВАЛИДЕН план (sizing.position_plan_v2 / buy_stop_preview): entry = entry_mid, stop = stop_loss, stop_pct = risk_pct, източник = структурен или таван.
    Невалиден план или stop >= entry → None (картата няма нива, причината е тази, която вече показва).
    """
    if not isinstance(plan, dict) or not plan.get("valid"):
        return None
    entry, stop, pct = plan.get("entry_mid"), plan.get("stop_loss"), plan.get("risk_pct")
    if not (_ok(entry) and _ok(stop) and _ok(pct)) or stop <= 0 or stop >= entry:
        return None
    adr = adr if _ok(adr) and adr > 0 else None
    warnings = []
    w = noise_warning(pct, adr)
    if w:
        warnings.append(w)
    return {"strategy": "canslim", "entry": round(float(entry), 2), "entry_label": entry_label,
            "stop": round(float(stop), 2), "stop_source": "cap" if plan.get("stop_capped") else "structural",
            "stop_source_text": plan.get("stop_basis") or "", "stop_pct": round(float(pct), 2), "adr_pct": adr,
            "regime_factor": float(regime_factor) if _ok(regime_factor) else 1.0, "warnings": warnings}


def kullamagi_levels(entry, adr, *, stop_adr: float, entry_label: str, expected_adr: float | None = None) -> dict | None:
    """
    Стоп за оразмеряване = вход × (1 − stop_adr × ADR/100) (stop_adr = 1.0 → "макс. 1×ADR"); по желание очакван стоп (expected_adr × ADR, 0.55 при breakout). Без режимен фактор:
    Qullamaggie е отделна стратегия, както и преди (старият размер не ползваше sizing_factor). Няма валиден вход/ADR → None.
    """
    if not (_ok(entry) and _ok(adr)) or entry <= 0 or adr <= 0:
        return None
    stop = round(entry * (1 - stop_adr * adr / 100), 2)
    if stop <= 0 or stop >= entry:
        return None
    out = {"strategy": "kullamagi", "entry": round(float(entry), 2), "entry_label": entry_label,
           "stop": stop, "stop_source": "adr", "stop_source_text": f"стоп за оразмеряване (макс. {stop_adr:g}×ADR)",
           "stop_pct": round(stop_adr * adr, 2), "adr_pct": round(float(adr), 2), "stop_note": STOP_NOTE_KMG,
           "regime_factor": 1.0, "regime_note": "отделна стратегия — без режимен фактор", "warnings": []}
    if expected_adr:
        exp = round(entry * (1 - expected_adr * adr / 100), 2)
        if 0 < exp < entry:
            out.update(expected_stop=exp, expected_stop_pct=round(expected_adr * adr, 2),
                       expected_stop_label=f"очакван стоп ({expected_adr:g}×ADR)")
    return out


def for_candidate(plan: dict | None, row: dict, regime_factor, entry_label: str) -> dict | None:
    """canslim_levels върху ред от скрийнъра (ADR от row['adr_pct']); никога не гърми — провал на нивата не чупи Action/Watchlist."""
    try:
        return canslim_levels(plan, (row or {}).get("adr_pct"), regime_factor, entry_label)
    except Exception as e:                                   # graceful: картата просто няма нива
        print(f"[levels] {(row or {}).get('ticker')}: {type(e).__name__}: {e}")
        return None
