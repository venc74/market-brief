"""
Имена на компании за показване (08.10.2026, code-queue и дребните от прегледа на брифа). Чисти функции.

  • prefer_long(short, long) — Yahoo реже shortName на 30–31 знака ("Corcept Therapeutics Incorporat", "Taiwan Semiconductor Manufactur", "Invesco S&P SmallCap Informatio"); когато shortName е отрязано начало
    на longName, се взима longName. Не пипа име, което не изглежда отрязано.
  • display_name(name, limit) — САМО за показване: маха правните окончания в края (Inc./Incorporated/Corp./Corporation/Holdings/Holding Company/Company/Co./Limited/Ltd/plc/N.V./S.A./SE/AG/A/S/S.A.B. de C.V., и повторени —
    "RELX PLC PLC" → "RELX") и водещото "The"; ако е зададен лимит, реже по граница на дума със «…», не по символ ("Corcept Therapeutics Incorporat" ≠ «Corcept Therapeutics…»). Запазеното име в данните
    (company, long_name) не се променя — сверяването на идентичност ползва пълните имена.
"""
from __future__ import annotations

import re

# правни окончания в края на името (сравнение без точки и запетаи, без значение на регистъра)
_LEGAL_TAIL = {"inc", "incorporated", "corp", "corporation", "holdings", "holding", "company", "co", "limited", "ltd", "plc", "nv", "sa", "se", "ag", "as"}
_LEGAL_PHRASE = re.compile(r"[,\s]+S\.?\s?A\.?\s?B\.?\s+de\s+C\.?\s?V\.?$", re.I)          # мексиканско "S.A.B. de C.V." (Coca Cola Femsa)
_TRUNC_MIN = 30                                                  # Yahoo реже shortName на 30–31 знака (в т.ч. краен интервал); под 30 знака отрязване не се подозира


def _norm_token(t: str) -> str:
    return re.sub(r"[.,]", "", t).lower()


def prefer_long(short: str | None, long: str | None) -> str | None:
    """
    shortName, освен ако е отрязано начало на longName: сурово ≥ 30 знака (Yahoo реже на 30–31, понякога с краен интервал) И longName започва със същото и е по-дълго. Име, което не изглежда отрязано
    ("Vanguard Long-Term Treasury ETF" — пълно, макар и 31 знака; "iShares Russell 2000 Index Fund"), не се пипа.
    """
    raw = short or ""
    short, long = raw.strip(), (long or "").strip()
    if not short:
        return long or None
    if not long or len(raw) < _TRUNC_MIN or len(long) <= len(short):
        return short
    return long if long.lower().startswith(short.lower()) else short


def strip_legal(name: str) -> str:
    """Маха правните окончания в края (повторени също) и водещото "The"; ако няма какво да остане — връща името както е."""
    name = _LEGAL_PHRASE.sub("", " ".join(name.split())) or name
    toks = name.split()
    while len(toks) > 1 and _norm_token(toks[-1].replace("/", "")) in _LEGAL_TAIL:
        toks.pop()
    if len(toks) > 1 and toks[0].lower() == "the":
        toks = toks[1:]
    out = " ".join(toks).rstrip(",").strip()
    return out or name


def cut_words(name: str, limit: int) -> str:
    """Реже по граница на дума до `limit` знака и добавя «…»; кратко име — както е. Една дълга дума без интервал се реже на символ."""
    if limit is None or len(name) <= limit:
        return name
    head = name[:limit + 1]
    sp = head.rfind(" ")
    cut = head[:sp] if sp >= max(8, limit // 2) else name[:limit]
    return cut.rstrip(" ,-–·") + "…"


def display_name(name: str | None, limit: int | None = None, strip: bool = True) -> str:
    if not name:
        return ""
    out = strip_legal(str(name)) if strip else str(name)
    return cut_words(out, limit) if limit else out
