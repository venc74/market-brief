"""
18.11.2026 (спешно, т. 3): проверка на ПРИЧИННИТЕ твърдения в макро разказа. Изречение, което казва, че нещо е станало заради нещо друго — „заради“, „поради“, „след като“,
„в резултат (на)“, „вследствие (на)“, „от“ след глагол за движение („VIX скочи от иранските удари“) и причинните глаголи („изстреляха VIX“, „което вдигна MOVE“,
„доведе до“) — остава САМО ако едно и също подадено заглавие съдържа и причината, и следствието. Иначе пада цялото изречение. Не се разпознава причината или следствието
(няма понятие от речника и латинска дума) → пада също (не може да се провери).

Реално, 18.11: „Иранските удари по американски бази в Залива изстреляха VIX с +11.13% …“ — заглавието „Iran says army targets U.S. drone and missile sites in Kuwait as Gulf
attacks mount“ съдържа Иран и ударите, но не VIX; нито едно заглавие не свързва двете → изречението пада.

Сравнението е двуезично: понятията (CONCEPTS + claim_check.CLAIMS + прилагателните за държавите) имат българска форма (в разказа) и английска (в заглавието); латинските думи
в разказа (VIX, Nvidia, Goldman) се търсят дословно в заглавието. Чиста функция; речникът расте само с потвърдени случаи (измерен върху историята — test_causal_check.py).
"""
from __future__ import annotations

import re

from src import claim_check

# (етикет, форми в разказа, опора в заглавието)
CONCEPTS: list[tuple[str, str, str]] = [
    ("VIX", r"\bVIX\b|волатилност\w*|индекс\w*\s+на\s+страха", r"\bVIX\b|volatil\w*|fear gauge|fear index"),
    ("петрол", r"петрол\w*|нефт\w*|\bBrent\b|\bWTI\b", r"\boil\b|crude|Brent|WTI|petroleum|OPEC|barrel\w*"),
    ("злато", r"злат\w*", r"\bgold\b|bullion"),
    ("сребро", r"сребр\w*", r"\bsilver\b"),
    ("мед", r"\bмед(?:та)?\b", r"copper"),
    ("суровини", r"суровин\w*|метал\w*", r"commodit\w*|metal\w*|copper|\bgold\b|\boil\b|silver"),
    ("природен газ", r"природн\w*\s+газ|\bгаз(?:ът|а)?\b", r"natural gas|\bgas\b|\bLNG\b"),
    ("долар", r"долар\w*|\bDXY\b", r"dollar|greenback|\bDXY\b|\bUSD\b"),
    ("доходност / облигации", r"доходност\w*|облигаци\w*|\bTreasur\w*|\d+-годишн\w*|десетгодишн\w*|двугодишн\w*|\byields?\b|лихвен\w*\s+процент\w*",
     r"yield\w*|Treasur\w*|\bbonds?\b|\bnotes?\b|gilt\w*"),
    ("MOVE", r"\bMOVE\b", r"\bMOVE\b|bond volatility|Treasury volatility|rates volatility"),
    ("акции / пазар", r"акци\w*|пазар\w*|индекс\w*|\bS&P\b|\bNasdaq\b|\bDow\b|\bRussell\b|Уолстрийт|Wall\s+Street|\bSPY\b|\bQQQ\b|\bIWM\b|\bRSP\b|бягство\w*\s+от\s+риска|риск-офф|risk-off",
     r"stock\w*|\bshares?\b|equit\w*|S&P|Nasdaq|\bDow\b|Russell|Wall Street|\bmarkets?\b|\bindex\w*|sell-?off|\brall\w*|risk"),
    ("технологии / AI / чипове", r"технолог\w*|\bAI\b|изкуствен\w*\s+интелект|чип\w*|полупроводни\w*|\bSMH\b|\bXLK\b|облачн\w*|data\s+cent\w*",
     r"\btech\w*|\bAI\b|artificial intelligence|\bchip\w*|semiconductor\w*|Nvidia|data cent\w*|cloud"),
    ("Fed / лихви", r"\bФед\w*|\bFed\b|Федерал\w*\s+резерв|лихв\w*|Уорш|\bWarsh\b|Пауъл|\bPowell\b|\bFOMC\b", r"\bFed\b|Federal Reserve|\bFOMC\b|\brates?\b|Warsh|Powell|monetary"),
    ("инфлация", r"инфлаци\w*|\bCPI\b|\bPCE\b|\bPPI\b", r"inflation|\bCPI\b|\bPCE\b|\bPPI\b|\bprices\b"),
    ("заетост", r"заетост\w*|безработиц\w*|работни\s+места|\bpayrolls\b|\bNFP\b|молби\w*\s+за\s+помощ\w*", r"\bjobs?\b|payroll\w*|employment|unemployment|jobless|labou?r"),
    ("жилища", r"жилищ\w*|строител\w*|ипотек\w*|недвижим\w*\s+имот\w*", r"\bhomes?\b|housing|mortgage\w*|builder\w*|real estate"),
    ("геополитика / удари", r"удар\w*|атак\w*|войн\w*|военн\w*|ракет\w*|дрон\w*|бомб\w*|конфликт\w*|геополити\w*|ескалаци\w*|\bбази\b|напрежени\w*",
     r"strike\w*|attack\w*|\bwar\b|military|missile\w*|drone\w*|bomb\w*|conflict|troops|escalat\w*|\bbases?\b|targets?\b|tension\w*"),
    ("крипто", r"биткойн\w*|крипто\w*|\bBTC\b|етериум\w*", r"bitcoin|crypto\w*|\bBTC\b|ether\w*"),
    ("отчети / печалби", r"отчет\w*|печалб\w*|приход\w*|прогноз\w*", r"earnings|results|revenue\w*|profit\w*|forecast\w*|guidance|outlook|\bbeats?\b|\bmiss\w*|quarter\w*"),
    ("IPO", r"\bIPO\b|първичн\w*\s+публичн\w*\s+предлагане|дебют\w*|листван\w*", r"\bIPO\b|debut\w*|listing|went public|go public"),
    ("банки / кредит", r"банк\w*|\bXLF\b|кредит\w*", r"\bbank\w*|lender\w*|credit"),
    ("енергетика", r"енергети\w*|\bXLE\b", r"energy|\boil\b|\bgas\b"),
    ("износ / търговия", r"износ\w*|внос\w*|търговск\w*", r"export\w*|import\w*|\btrade\b"),
    ("САЩ (прил.)", r"американск\w*|\bСАЩ\b|Вашингтон\w*", r"\bU\.?S\.?\b|American|Washington|Pentagon|Trump"),
    ("Иран (прил.)", r"иранск\w*", r"Iran\w*|Tehran"),
    ("Китай (прил.)", r"китайск\w*", r"China|Chinese|Beijing|\bXi\b"),
    ("Русия (прил.)", r"руск\w*", r"Russia\w*|Moscow|Kremlin|Putin"),
    ("Израел (прил.)", r"израелск\w*", r"Israel\w*"),
    ("Япония (прил.)", r"японск\w*", r"Japan\w*|Tokyo|\byen\b"),
    ("Европа (прил.)", r"европейск\w*", r"\bEU\b|Europe\w*|Brussels|\bECB\b"),
    ("Залива", r"\bЗалив\w*", r"\bGulf\b|Kuwait|Saudi|Qatar|\bUAE\b|Bahrain|Hormuz"),
]
_ALL = [(lab, re.compile(bg, re.I), re.compile(en, re.I)) for lab, bg, en in CONCEPTS] + \
       [(lab, re.compile(bg, re.I), re.compile(src, re.I)) for lab, bg, src in claim_check.CLAIMS]
# латинските думи в разказа (имена, тикъри), които не са понятие сами по себе си
_LATIN = re.compile(r"\b[A-Z][A-Za-z0-9&'’\-]{2,}\b")
_LATIN_SKIP = {"RS", "SPY", "QQQ", "IWM", "RSP", "ETF", "EPS", "YoY", "MoM", "DMA", "SMA", "RoC", "ROC", "Offensive", "Defensive", "Cash"}

# маркерите: (вид, regex). Причината е СЛЕД маркера (освен при причинните глаголи — преди него).
_CONNECT = re.compile(r"\b(?:заради|поради|вследствие(?:\s+на)?|в\s+резултат(?:\s+на)?|след\s+като|благодарение\s+на|тъй\s+като|защото|понеже)\b", re.I)
_MOVE = (r"\b(?:скочи\w*|поскочи\w*|подскочи\w*|падна\w*|спадна\w*|поскъпна\w*|поевтиня\w*|отскочи\w*|нарасна\w*|се\s+покачи\w*|се\s+повиши\w*|се\s+понижи\w*"
         r"|се\s+срина\w*|срина\w*|изстреля\w*)")                              # само глаголи: „натиск от доходностите“ (съществително) не е проверимо твърдение
# „от“ е причинно само след глагол / съществително за движение и пред съществително, не пред число, ниво или време („спад от 13%“, „от върха“, „от юли“)
_OT = re.compile(_MOVE + r"(?:\s+(?:с|със)\s+[+\-−]?\d[\d.,]*\s*(?:%|б\.\s?п\.|пункта)?)?\s+от\s+(?![+\-−]?[$€£¥]?\d|върх|дън|ниво|равнищ|началото|предишн|вчера|миналат|последн|седмиц|месец|годин|рекорд"
                 r"|януари|февруари|март|април|май|юни|юли|август|септември|октомври|ноември|декември|тогава|там|него|нея|тях|SPY|сесия)", re.I)
_VERB = re.compile(r"(?<!\bсе\s)\b(?:изстреля(?:ха)?|предизвика(?:ха)?|доведе(?:ха)?\s+до|тласна(?:ха)?|повлия(?:ха)?|удариха|натисна(?:ха)?|притисна(?:ха)?|вдигна(?:ха)?|свали(?:ха)?"
                   r"|срина(?:ха)?|подкрепи(?:ха)?|понижи(?:ха)?|повиши(?:ха)?)\b(?!\s+се\b)", re.I)   # „се срина“ / „срина се“, „се понижи“ — непреходни, не са причина
# глаголите, които са и действие („CoreWeave вдигна guidance“, „Fed понижи лихвите“) — причинни само когато следствието е пазарен актив
_AMBIG = re.compile(r"^(?:вдигна|свали|понижи|повиши|подкрепи)", re.I)
_ASSETS = {"VIX", "петрол", "злато", "сребро", "мед", "суровини", "природен газ", "долар", "доходност / облигации", "MOVE", "акции / пазар"}
_CLAUSE = re.compile(r"\s[—–]\s|;\s|:\s|,\s")
_REL = re.compile(r"^\s*(?:което|която|които|това|те|той|тя)\b", re.I)
_SENT = re.compile(r"(?<=[.!?…])\s+(?=[A-ZА-Я„\"(\d])")


def concepts(span: str) -> list[tuple[str, re.Pattern]]:
    """Понятията в текста на разказа → [(етикет, regex за заглавието)]; + латинските думи (дословно). Чиста функция."""
    out = [(lab, en) for lab, bg, en in _ALL if bg.search(span or "")]
    for w in _LATIN.findall(span or ""):
        w = w.strip("'’")
        if w not in _LATIN_SKIP and not any(lab == w for lab, _ in out):
            out.append((w, re.compile(r"\b" + re.escape(w.split("'")[0].split("’")[0]) + r"\w*", re.I)))
    return out


def _clause_bounds(sent: str, pos: int) -> tuple[int, int]:
    """Началото и краят на клаузата около позицията (по „, “, „; “, „: “, „ — “)."""
    starts = [m.end() for m in _CLAUSE.finditer(sent) if m.end() <= pos]
    ends = [m.start() for m in _CLAUSE.finditer(sent) if m.start() >= pos]
    return (starts[-1] if starts else 0), (ends[0] if ends else len(sent))


def _prev_clause(sent: str, start: int) -> str:
    prev = [m for m in _CLAUSE.finditer(sent) if m.end() <= start]
    if not prev:
        return ""
    end = prev[-1].start()
    s0 = [m.end() for m in _CLAUSE.finditer(sent) if m.end() <= end]
    return sent[(s0[-1] if s0 else 0):end]


def claims(sent: str) -> list[dict]:
    """Причинните твърдения в изречението → [{kind, marker, cause, effect}]. Чиста функция."""
    out = []
    for m in _CONNECT.finditer(sent):
        a, b = _clause_bounds(sent, m.start())
        cause = sent[m.end():b]
        effect = sent[a:m.start()]
        if not effect.strip(" ,—–;:"):
            if a > 0:                                                            # „…, защото X“ — следствието е предишната клауза
                effect = _prev_clause(sent, a) if _prev_clause(sent, a).strip() else sent[:a]
            else:                                                                # „Заради X, Y …“ / „След като X, Y …“ — следствието е следващата клауза
                nxt = [x for x in _CLAUSE.finditer(sent) if x.start() >= b]
                effect = sent[b:(nxt[1].start() if len(nxt) > 1 else len(sent))]
        out.append({"kind": "дума", "marker": m.group(0), "cause": cause, "effect": effect})
    for m in _OT.finditer(sent):
        a, b = _clause_bounds(sent, m.start())
        ot = sent.lower().rfind(" от ", m.start(), m.end() + 1)
        out.append({"kind": "„от“", "marker": sent[m.start():m.end()].strip(), "cause": sent[ot + 4 if ot >= 0 else m.end():b], "effect": sent[a:m.end()]})
    for m in _VERB.finditer(sent):
        a, b = _clause_bounds(sent, m.start())
        cause, effect = sent[a:m.start()], sent[m.end():b]
        if _AMBIG.match(m.group(0)) and not any(lab in _ASSETS for lab, _ in concepts(effect)):
            continue                                                             # действие, не причина за пазарно движение
        if _REL.match(cause) or not cause.strip():
            cause = _prev_clause(sent, a) + " " + cause
        out.append({"kind": "глагол", "marker": m.group(0), "cause": cause, "effect": effect})
    return out


def supported(claim: dict, headlines: list[str]) -> tuple[bool, str]:
    """
    (подкрепено ли е, защо не). Причината и следствието разпознати и различни → нужно е ЕДНО заглавие с понятие от причината И понятие от следствието. Причината без собствено
    понятие („… е на 5.12%, след като за 5 сесии добави 25.7 б.п.“ — същият подлог; „AAPL предупреди … заради растящите разходи за памет“) → не е проверима връзка между две
    назовани неща — остава. Разпозната е само причината → нужно е заглавие поне с нея (иначе пада: причината не е в подадените новини). Чиста функция.
    """
    cs, es = concepts(claim["cause"]), concepts(claim["effect"])
    elab = {l for l, _ in es}
    cs_own = [(l, rx) for l, rx in cs if l not in elab]
    if not cs_own:
        return True, ""
    if not es:
        if any(any(rx.search(h) for _, rx in cs_own) for h in headlines):
            return True, ""
        return False, f"причината ({', '.join(l for l, _ in cs_own[:3])}) я няма в нито едно подадено заглавие"
    for h in headlines:
        if any(rx.search(h) for _, rx in cs_own) and any(rx.search(h) for _, rx in es):
            return True, ""
    return False, f"нито едно заглавие не свързва {', '.join(l for l, _ in cs_own[:3])} със {', '.join(l for l, _ in es[:3])}"


def headlines_of(news: list | None, crypto: dict | None = None) -> list[str]:
    """Заглавията, подадени на модела — основното и „също“ на всяка новина и крипто новините, всяко поотделно."""
    out = []
    for n in list(news or []) + list((crypto or {}).get("items") or []):
        if isinstance(n, dict):
            out += [n.get("headline") or ""] + [a.get("headline") or "" for a in n.get("also") or [] if isinstance(a, dict)]
    return [h for h in out if h]


def check(text: str, news: list | None, verbs: bool = True, crypto: dict | None = None) -> tuple[str, list[dict]]:
    """
    Разказът → (без неподкрепените причинни изречения, [{sentence, marker, kind, why}]). verbs=False — без причинните глаголи (само думите и „от“). Абзаците се пазят. Чиста функция.
    """
    if not isinstance(text, str) or not text.strip():
        return text, []
    hs = headlines_of(news, crypto)
    removed, paras = [], []
    for para in re.split(r"(\n\s*\n)", text):
        if not para.strip() or re.fullmatch(r"\n\s*\n", para):
            paras.append(para)
            continue
        kept = []
        for sent in _SENT.split(para.strip()):
            bad = None
            for c in claims(sent):
                if c["kind"] == "глагол" and not verbs:
                    continue
                ok, why = supported(c, hs)
                if not ok:
                    bad = {"sentence": sent, "marker": c["marker"], "kind": c["kind"], "why": why}
                    break
            (removed.append(bad) if bad else kept.append(sent))
        paras.append(" ".join(kept))
    out = re.sub(r"(\n\s*\n){2,}", "\n\n", "".join(paras)).strip()
    return out, removed
