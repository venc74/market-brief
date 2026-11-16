"""
16.11.2026 (пакет 16.11, т. 1): проверка на ТВЪРДЕНИЯТА в AI текста — кой какво е направил (институция, държава, лице, мярка), не ефектът. Изречение, което назовава институция /
държава / мярка, която я няма в текста, подаден на модела (заглавия, резюмета, „защо“, данните), пада цяло — както проверката за термини (ai_brief.check_market_terms).

Реално 16.11: „защо“ на новината за Nvidia — „Натискът на Министерството на финансите … експортните ограничения към Китай и изискването за външен CEO“ — под заглавието
„Trump administration to name Nvidia, other AI firms as US 'national champions'“. Фактите НЕ са измислени: те са от резюмето на FT към заглавието, което моделът избра („Bessent
says Nvidia needs ‘shake-up’ with external CEO — US Treasury secretary demands to know if chipmaker is complying with restrictions on exports to China“); кодът смени основното
заглавие с друго от групата (по-надеждния източник, Reuters) — затова от 16.11 основното остава заглавието на модела (news_aggregator.pick_verbatim), а тази проверка е втората защита.

Ефектът за пазарите (активи, сектори, ETF-и, посока) не е твърдение за факт и не се проверява — моделът е помолен да го пише. Числата се проверяват отделно
(news_aggregator._why_numbers, ai_brief.check_narrative_numbers). Чиста функция; речникът — CLAIMS.
"""
from __future__ import annotations

import re

# (етикет, българските форми в AI текста, опората в източника — английски или български). Речникът расте само с потвърдени случаи; измерен върху историята (виж тестa).
CLAIMS: list[tuple[str, str, str]] = [
    ("Министерството на финансите на САЩ", r"министерств\w*\s+на\s+финансите|финансов\w*\s+министър|министър\w*\s+на\s+финансите",
     r"treasury|bessent|finance minist|министерств\w*\s+на\s+финансите|финансов\w*\s+министър|министър\w*\s+на\s+финансите|бесънт"),
    ("Министерството на търговията на САЩ", r"министерств\w*\s+на\s+търговията|търговск\w*\s+министър|министър\w*\s+на\s+търговията",
     r"commerce|lutnick|министерств\w*\s+на\s+търговията|търговск\w*\s+министър|лътник"),
    ("експортни ограничения", r"\bекспорт\w*\s+(?:ограничени|контрол|забран|рестрикци)\w*|\bограничени\w*\s+(?:върху|за|на)\s+(?:износа|експорта)",
     r"export\w*|curb\w*|експорт\w*|износ\w*"),
    ("смяна / избор на CEO", r"\b(?:външен|нов\w*)\s+(?:CEO|изпълнителен\s+директор|главен\s+изпълнителен)|\bоставк\w*\s+на\s+(?:CEO|изпълнителния)",
     r"\bCEO\b|chief executive|resign|exit|step(?:s|ped)? down|изпълнителен\s+директор|оставк\w*"),
    ("санкции", r"\bсанкци\w*", r"sanction\w*|санкци\w*|blacklist\w*|entity list|ban\b|banned"),
    ("мита", r"\bмит(?:а|ата|о|ото)\b|\bтарифи\w*\s+(?:върху|срещу|за\s+вноса)|\bтърговск\w+\s+войн\w*", r"tariff\w*|levy|levies|duties|trade (?:war|curbs?|dispute|tension\w*|conflict)|retaliat\w*|мит(?:а|ата|о)|тарифи\w*"),
    ("антитръст", r"\bантитръст\w*|\bантимонопол\w*", r"antitrust|anti-trust|monopol\w*|\bDOJ\b|\bFTC\b|competition (?:law|regulator|probe)|lawsuit|attorneys general|\bAGs\b|антитръст\w*|антимонопол\w*"),
    ("разследване", r"\bразследван\w*", r"investigat\w*|probe\w*|inquir\w*|scrutiny|subpoena|testify|разследван\w*"),
    ("ЕЦБ", r"\bЕЦБ\b|Европейската\s+централна\s+банка", r"\bECB\b|European Central Bank|Lagarde|ЕЦБ|Европейската централна банка"),
    ("Bank of Japan", r"\bBoJ\b|\bBOJ\b|Bank\s+of\s+Japan|Японската\s+централна\s+банка", r"\bBOJ\b|Bank of Japan|Ueda|BoJ|Японската централна банка"),
    ("Bank of England", r"\bBoE\b|Bank\s+of\s+England|Английската\s+централна\s+банка", r"\bBOE\b|Bank of England|Bailey|BoE"),
    ("ОПЕК", r"\bОПЕК\b|\bOPEC\b", r"OPEC|ОПЕК"),
    ("Конгреса / Сената", r"\bКонгрес\w*|\bСенат\w*|Камарата\s+на\s+представителите", r"Congress|Senate|House|Capitol|lawmaker\w*|legislat\w*|Конгрес\w*|Сенат\w*"),
    ("Белия дом", r"Белия\s+дом", r"White House|Trump|administration|Белия дом|Тръмп"),
    # държавите — само съществителното (кой е действал); прилагателното („китайски EV сектор“, „британски yields“) описва засегнатите активи, не твърди факт
    ("Китай", r"\bКитай\b|\bКитая\b|\bПекин\b", r"China|Chinese|Beijing|Xi\b|Китай|китайск\w*|Пекин"),
    ("Русия", r"\bРусия\b|\bКремъл\w*|\bМосква\b", r"Russia\w*|Moscow|Kremlin|Putin|Руси\w*|руск\w*|Москва|Кремъл"),
    ("Иран", r"\bИран\b|\bТехеран\b", r"Iran\w*|Tehran|Иран\w*|Техеран"),
    ("Израел", r"\bИзраел\b", r"Israel\w*|Израел\w*"),
    ("Украйна", r"\bУкрайна\b|\bКиев\b", r"Ukrain\w*|Kyiv|Kiev|Украйн\w*|Киев"),
    ("Тайван", r"\bТайван\b", r"Taiwan\w*|TSMC|Тайван\w*"),
    ("Хормуз", r"\bХормуз\w*|\bОрмуз\w*", r"Hormuz|Хормуз\w*|Ормуз\w*"),
    ("Япония", r"\bЯпония\b|\bТокио\b", r"Japan\w*|Tokyo|Nikkei|BOJ|yen|Япони\w*|японск\w*|йен\w*"),
    ("Европа / ЕС", r"\bЕС\b|Европейския\s+съюз|Европейската\s+комисия|\bБрюксел\b", r"\bEU\b|European|Europe|Brussels|\bЕС\b|Европейск\w*|Брюксел"),
    ("Германия", r"\bГермания\b|\bБерлин\b", r"German\w*|Berlin|Bund|DAX|Merz|Германи\w*|германск\w*"),
    ("Великобритания", r"\bВеликобритания\b|Обединеното\s+кралство|\bЛондон\b", r"Brit\w*|\bUK\b|U\.K\.|England|London|Gilt|FTSE|Великобритани\w*|британск\w*"),
    ("Индия", r"\bИндия\b", r"India\w*|Indian|Rupee|Инди\w*|индийск\w*"),
    ("съдебно решение", r"\b(?:съд\w*|съдия|съдебни\s+заседатели)\s+(?:реши|постанови|отхвърли|блокира|отмени)\w*|\bсъдебн\w*\s+решени\w*", r"court|judge|jury|ruling|ruled|lawsuit|verdict|съд\w*"),
    ("съкращения", r"\bсъкращени\w*\s+(?:на\s+)?(?:работни\s+места|служители|персонал)|\bсъкраща\w*\s+(?:служители|работни\s+места)", r"layoff\w*|job cuts?|cut\w*\s+(?:\S+\s+){0,3}(?:jobs|staff|workforce)|redundanc\w*|съкращени\w*"),
    ("придобиване / сливане", r"\bпридобиване\w*|\bпридобие\b|\bсливане\w*", r"acqui\w*|merger\w*|merge\w*|takeover|buyout|purchase\w*|\bbuy\w*|bought|deal|bid\b|offer|stake|придобива\w*|сливане\w*|сделк\w*"),
    ("банкрут", r"\bбанкрут\w*|\bфалит\w*|\bнесъстоятелност\w*", r"bankrupt\w*|Chapter 11|insolven\w*|default\w*|банкрут\w*|фалит\w*"),
]
_COMPILED = [(lab, re.compile(bg, re.I), re.compile(src, re.I)) for lab, bg, src in CLAIMS]
_SENT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-Я„\"(\d])")


# предположение, не твърдение: „потенциални санкции“, „рискува да доведе до нови ограничения върху износа“, „може да засегне“ — до 5 думи преди назованото
_HEDGE = re.compile(r"(?:потенциал\w*|възможн\w*|евентуал\w*|риск\w*|заплах\w*|опасени\w*|страх\w*|може\s+да|могат\s+да|би\b|биха|ако|дали)\s+(?:\S+\s+){0,5}$", re.I)


def unsupported(sentence: str, source: str) -> list[str]:
    """Етикетите на твърденията в изречението без опора в source (предположенията — _HEDGE — не се броят). Чиста функция."""
    out = []
    for lab, bg, src in _COMPILED:
        if src.search(source or ""):
            continue
        if any(not _HEDGE.search((sentence or "")[:m.start()]) for m in bg.finditer(sentence or "")):
            out.append(lab)
    return out


def check(text: str, source: str) -> tuple[str, list[dict]]:
    """
    Текстът (абзаците се пазят) → (поправеният, [{sentence, claims}]). Изречение с твърдение без опора в source пада цяло; празен остатък → "". Чиста функция.
    """
    if not isinstance(text, str) or not text.strip():
        return text, []
    removed: list[dict] = []
    paras = []
    for para in re.split(r"(\n\s*\n)", text):
        if not para.strip() or re.fullmatch(r"\n\s*\n", para):
            paras.append(para)
            continue
        kept = []
        for sent in _SENT.split(para.strip()):
            bad = unsupported(sent, source)
            if bad:
                removed.append({"sentence": sent, "claims": bad})
            else:
                kept.append(sent)
        paras.append(" ".join(kept))
    out = "".join(paras)
    out = re.sub(r"(\n\s*\n){2,}", "\n\n", out).strip()
    return out, removed
