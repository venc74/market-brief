"""
Помощна част за COT тестовете, които НЕ са за идентичността на компанията (08.10.2026).

Преди 08.10 суровият отговор на модела нямаше company_claim, а lookup-ите в тестовете нямат сектор/валута на отчитане. Проверките за идентичност (company_claim
срещу името в Yahoo), за липсващ сектор и за не-USD отчитащи се са в cot_theses.cross_gate и имат СВОЙ тест — test_cot_claims.py. Тук ги неутрализираме САМО
в тестовете за други правила (знак, mixed, кеш, значки…), за да не ги чупят: твърдението за компанията става името от lookup-а, липсващият сектор/валута се попълват.
ETF правилото (фонд в cross) остава ВКЛЮЧЕНО — то е част от поведението, което тези тестове вече описват.
"""
import copy


def neutral_identity(ai_brief):
    """Подменя ai_brief._cot_table.cross_gate с обвивка: company_claim = името от lookup-а, сектор "Test sector" и валута "USD" по подразбиране."""
    orig = getattr(ai_brief._cot_table, "_orig_cross_gate", None) or ai_brief._cot_table.cross_gate
    ai_brief._cot_table._orig_cross_gate = orig

    def gate(t, lookup, market):
        lk = {**lookup, "sector": lookup.get("sector") or "Test sector", "financial_currency": lookup.get("financial_currency") or "USD"}
        return orig({**t, "company_claim": lk.get("name") or t.get("ticker")}, lk, market)

    ai_brief._cot_table.cross_gate = gate


def claimed(raw):
    """Дълбоко копие на суров отговор (списък от тикъри или речник пазар → списък), в което всеки тикър получава company_claim = company (формата преди 08.10)."""
    raw = copy.deepcopy(raw)
    rows = raw.values() if isinstance(raw, dict) else [raw]
    for lst in rows:
        for t in lst or []:
            if isinstance(t, dict) and "company_claim" not in t:
                t["company_claim"] = t.get("company") or t.get("ticker")
    return raw
