"""
Персонален AI Инвестиционен Бриф — централна конфигурация.
Всички правила от Секция 8 на спека живеят тук, не са пръснати из кода.
"""
import os

# ── Портфолио и риск (Секция 3.7) ────────────────────────────────────────
PORTFOLIO_SIZE = float(os.getenv("PORTFOLIO_SIZE", 100_000))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", 1.0))   # % от портфолиото
MIN_REWARD_RISK = 2.0                                              # минимум 2:1

# ── Твърди правила (Секция 8) ────────────────────────────────────────────
MAX_ACTION_TICKERS = 5            # качество над количество
EARNINGS_BLACKOUT_DAYS = 5        # без препоръки 5 работни дни преди earnings
VIX_DEFENSIVE_THRESHOLD = 30.0    # над това → Defensive + sizing × 0.5
DEFENSIVE_SIZING_FACTOR = 0.5
MAX_PER_SECTOR = 2                # макс 2 акции от един сектор
MIN_PRICE = 10.0                  # без акции под $10
MIN_MARKET_CAP = 500_000_000      # без mcap под $500M
# FIX 2026-08-02 (timeout guard): максимално чакане на извикващия код за
# yf.Ticker(sym).info fetch, през net_utils.fetch_with_timeout() (ai_brief.py,
# magic_formula.py, screener.py). yfinance вече слага собствен default
# timeout=30s вътрешно — това е допълнителна горна граница, за да не се
# натрупват 30s×N закъснения в secuential scan на десетки тикъри при
# систематично забавен Yahoo.
YF_INFO_TIMEOUT_SEC = float(os.getenv("YF_INFO_TIMEOUT_SEC", 10))

# ── Технически критерии (Секция 3, Слой 3) ──────────────────────────────
BREAKOUT_VOLUME_MULT = 1.5        # 1.5x среден 50-дневен обем
MAX_PCT_BELOW_PIVOT = 5.0         # не повече от 5% под pivot
WEINSTEIN_MA_WEEKS = 30           # 30-седмична MA (= 150 дневни сесии)

# ── Фундаментални критерии (CANSLIM) ─────────────────────────────────────
MIN_EPS_GROWTH_YOY = 25.0         # %
MIN_REVENUE_GROWTH_YOY = 20.0     # %
MIN_ROE = 17.0                    # %

# ── Пазарен термометър ────────────────────────────────────────────────────
VIX_RISK_ON = 20.0
VIX_RISK_OFF = 25.0
# FIX 2026-08-02 (точка 11): mirroring MOVE_SPIKE_WEEKLY_DELTA — статичният VIX
# праг по-долу хваща само абсолютното ниво, не скоростта на промяна (AI-то само
# отбеляза методологичната дупка на 24.07.2026: VIX 18.7 "зелен" по стойност
# при +24.4% 5-дневна промяна). Калибровано на 2г реална VIX история: 90-ти
# персентил на 5-дневната % промяна е ~21.1%, 95-ти ~29.7% — 20% сяда точно под
# 90-ти персентил (хваща реално необичайни скокове, не нормален шум) и улавя и
# двата наблюдавани реални случая (24.07: +24.4%, 30.07: +23%), докато оставя
# 28.07 (+13%, ~78-ми персентил, нормален шум) незасегнат.
VIX_SPIKE_WEEKLY_PCT = float(os.getenv("VIX_SPIKE_WEEKLY_PCT", 20.0))

# ── API ключове (от GitHub Secrets / .env) ───────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")        # newsapi.org, optional
# TRADIER_API_KEY / TRADIER_BASE — виж v2 секцията по-долу (заедно с коментара им)

# ── Имейл доставка ────────────────────────────────────────────────────────
EMAIL_METHOD = os.getenv("EMAIL_METHOD", "smtp")    # "smtp" | "sendgrid"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://venc74.github.io/market-brief/")

# ── Claude модел ──────────────────────────────────────────────────────────
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── AI batch синтез (ticker_narratives) ───────────────────────────────────
# Per-ticker наративите се правят на batch-ове, а не в едно извикване, защото
# фиксиран max_tokens никога не е safe за неизвестен брой финалисти — при много
# кандидати JSON-ът се отрязва по средата (Unterminated string). Малки batch-ове
# гарантират достатъчен token budget на batch, независимо от общия брой тикъри.
AI_BATCH_SIZE = int(os.getenv("AI_BATCH_SIZE", 5))           # тикъри на API извикване
AI_BATCH_MAX_TOKENS = int(os.getenv("AI_BATCH_MAX_TOKENS", 8000))  # budget на batch

# ── Пътища ────────────────────────────────────────────────────────────────
import pathlib
ROOT = pathlib.Path(__file__).parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
IV_HISTORY_FILE = DATA_DIR / "iv_history.json"

# ── Секторни ETF-и за ротационен анализ (Слой 2) ─────────────────────────
SECTOR_ETFS = {
    "XLK": "Технологии", "XLE": "Енергетика", "XLF": "Финанси",
    "XLV": "Здравеопазване", "XLI": "Индустрия", "XLB": "Материали",
    "XLY": "Потребителски (циклични)", "XLP": "Потребителски (защитни)",
    "XLU": "Комунални услуги", "XLRE": "Недвижими имоти", "XLC": "Комуникации",
    "ITA": "Отбрана", "GDX": "Златодобив", "URA": "Уран/ядрена", "TAN": "Соларна",
    "SMH": "Полупроводници", "XBI": "Биотех", "KOL_PROXY_BTU": "Въглища (proxy)",
}


# ══════════════════════════════════════════════════════════════════════════
# v2 НАДСТРОЙКА — нови настройки (additive, нищо отгоре не е пипано)
# ══════════════════════════════════════════════════════════════════════════

# ── 3.1 Magic Formula Cross-Check ────────────────────────────────────────
MAGIC_FORMULA_TOP_N = int(os.getenv("MAGIC_FORMULA_TOP_N", 50))
# Независим референтен универс за Magic Formula (за да е cross-check-ът наистина
# независим от CANSLIM). Ликвидни large/mid-cap имена през сектори. Редактируем.
MAGIC_FORMULA_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMD", "AVGO", "ORCL", "ADBE",
    "CRM", "INTC", "QCOM", "TXN", "MU", "AMAT", "MCHP", "CSCO", "IBM",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "V", "MA", "PYPL",
    "UNH", "JNJ", "PFE", "MRK", "ABBV", "LLY", "TMO", "ABT", "BMY",
    "XOM", "CVX", "COP", "SLB", "OXY", "BTU", "LNG",
    "CAT", "DE", "HON", "GE", "LMT", "RTX", "NOC", "BA",
    "WMT", "COST", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE", "PG", "KO", "PEP",
    "DIS", "NFLX", "CMCSA", "T", "VZ", "TMUS",
    "CCJ", "VST", "CEG", "F", "GM", "UPS", "FDX",
]

# ── 5. Геополитически тематични кошници (thesis monitor) ──────────────────
# status: "active" — макро тригер е налице; "structural" — дългосрочен попътен
# вятър без нужда от тригер; "watch" — следи се ръчно (законодателство/събитие).
THESIS_BASKETS = [
    {
        "name": "Въглища и LNG",
        "tickers": ["BTU", "HCC", "AMR", "CEIX", "TELL", "LNG"],
        "default_status": "watch",
        "trigger": "oil_shock",
        "chain": ("Петролен шок или напрежение в Близкия изток → скок в цената на "
                  "енергията → въглищата и LNG поемат търсенето, което петролът не "
                  "може → маржовете на тези производители се разширяват рязко."),
    },
    {
        "name": "Ядрена енергия",
        "tickers": ["VST", "CEG", "OKLO", "CCJ", "DNN", "NNE"],
        "default_status": "structural",
        "trigger": None,
        "chain": ("AI data center-ите гладуват за стабилна базова мощност 24/7 → "
                  "ядрената е единственият въглеродно-неутрален източник, който я "
                  "дава → дългосрочно търсене на уран и реакторни оператори."),
    },
    {
        "name": "Отбрана и дронове",
        "tickers": ["LMT", "RTX", "NOC", "SWMR"],
        "default_status": "watch",
        "trigger": "geopolitical_stress",
        "chain": ("Геополитическа ескалация → държавите вдигат отбранителни бюджети → "
                  "поръчки с многогодишен backlog за големите изпълнители → предвидим "
                  "приходен поток независим от икономическия цикъл."),
    },
    {
        "name": "Крипто регулация (CLARITY Act)",
        "tickers": ["CRCL", "COIN", "HOOD", "BLSH"],
        "default_status": "watch",
        "trigger": None,
        "chain": ("Ясна законодателна рамка (CLARITY Act) → институциите получават "
                  "регулаторна сигурност → приток на капитал към регулирани крипто "
                  "борси и custody → борсите и брокерите печелят на обем."),
    },
    {
        "name": "Полупроводници и AI инфраструктура",
        "tickers": ["AVGO", "AMAT", "MCHP"],
        "default_status": "structural",
        "trigger": None,
        "chain": ("AI build-out → търсене не само на GPU, а на цялата верига: mature-"
                  "node чипове, оборудване за производство, liquid cooling, мрежи и "
                  "захранване → вторичните доставчици печелят с по-малко конкуренция."),
    },
    {
        "name": "Финанси при стръмна крива",
        "tickers": ["JPM", "BAC"],
        "default_status": "watch",
        "trigger": "curve_steepening",
        "chain": ("Кривата се разкривява (дълъг край нагоре) → банките заемат евтино "
                  "на късо и кредитират скъпо на дълго → нетният лихвен марж се "
                  "разширява → пряко по-висока доходност за банковия сектор."),
    },
]

# ── Toggle-и за новите скрейпъри (за лесно изключване при проблем) ─────────
ENABLE_MAGIC_FORMULA = os.getenv("ENABLE_MAGIC_FORMULA", "1") == "1"
ENABLE_BORROW_DATA = os.getenv("ENABLE_BORROW_DATA", "1") == "1"
ENABLE_UNUSUAL_OPTIONS = os.getenv("ENABLE_UNUSUAL_OPTIONS", "1") == "1"
ENABLE_SPLITS_CALENDAR = os.getenv("ENABLE_SPLITS_CALENDAR", "1") == "1"


# ── Dataroma · Superinvestor Moves ────────────────────────────────────────
# Минимална стойност на позицията, за да се брои „значима" покупка (само за
# основния Moves feed — high-conviction new positions ползва % на портфейл,
# не $ праг, виж DATAROMA_MIN_NEW_POSITION_PCT по-долу).
DATAROMA_MIN_VALUE = float(os.getenv("DATAROMA_MIN_VALUE", 10_000_000))   # $10M
# Ако True: при fallback към allact.php (без стойности) се отхвърлят редовете
# без известна стойност. По подразбиране False — по-добре да видиш хода.
DATAROMA_STRICT_VALUE = os.getenv("DATAROMA_STRICT_VALUE", "0") == "1"
ENABLE_DATAROMA = os.getenv("ENABLE_DATAROMA", "1") == "1"
# FIX 2026-08-17: top-N позиции НА МЕНИДЖЪР за основния Moves feed (не global
# top-N по $ стойност) — Berkshire's позиции ($10B+ всяка) системно изяждаха
# всичките 5 dashboard слота дори в дни, когато 3-4 други мениджъри имаха
# съвсем реални, валидни редове точно под Buffett-овите в същия dataset
# (потвърдено емпирично, 2026-08-17 диагностика). DATAROMA_MOVES_DISPLAY_LIMIT
# е таванът СЛЕД top-N-per-manager селекцията + dedup по тикър (замества
# старото hardcoded [:5] в темплейта — единствен източник на истината в код).
DATAROMA_TOP_PER_MANAGER = int(os.getenv("DATAROMA_TOP_PER_MANAGER", 2))
DATAROMA_MOVES_DISPLAY_LIMIT = int(os.getenv("DATAROMA_MOVES_DISPLAY_LIMIT", 8))
# High-conviction "нова позиция" сигнал — CUSIP отсъства в предишния filing
# И value >= този % от ТЕКУЩИЯ портфейл на мениджъра (не $ праг — 2% от
# по-малък фонд, напр. Pabrai/Dalal Street ~$327M портфейл, е ~$6.5M, под
# DATAROMA_MIN_VALUE $10M; $ праг тук би изтрил точно small-fund сигналите).
DATAROMA_MIN_NEW_POSITION_PCT = float(os.getenv("DATAROMA_MIN_NEW_POSITION_PCT", 2.0))
# "Major exit" сигнал — CUSIP присъствал в ПРЕДИШНИЯ filing на >= този % от
# тогавашния портфейл, отсъства напълно в текущия. Изчислява се САМО за
# filing_status="active" мениджъри (виж DATAROMA_STALE_FILER_DAYS) — иначе
# "фондът затвори" (Burry/Scion, потвърдено 2026-08-17) би се смесило с
# "продадена конкретна позиция", две различни събития.
DATAROMA_MAJOR_EXIT_PCT = float(os.getenv("DATAROMA_MAJOR_EXIT_PCT", 10.0))
# Мениджър без нов 13F-HR над този брой дни → filing_status="stopped", major
# exit логиката се прескача изцяло за него (виж по-горе). ~135 дни е worst-
# case gap между два НАВРЕМЕННИ тримесечни filing-а (45-дневен deadline след
# края на тримесечието) — 165 дава разумен buffer над това, без да е толкова
# хлабав, че истински спрял мениджър (Burry, последен filing 2025-11-03,
# >280 дни към 2026-08-17) да остане незасечен.
DATAROMA_STALE_FILER_DAYS = int(os.getenv("DATAROMA_STALE_FILER_DAYS", 165))
# CIK номера — виж DATAROMA_CIK по-долу (Секция EDGAR 13F) за пълния,
# верифициран списък от 16 мениджъра. DATAROMA_MANAGERS (dataroma.com URL
# кодове) премахнат 2026-08-17 — беше практически мъртъв fallback код
# (стигаше се до него само ако EDGAR върнеше 0 за ВСИЧКИ CIK-ове едновременно)
# в ДРУГА ID система от CIK, синхронизирането му би удвоило поддръжката за
# нулева практическа полза; _allact_buys() (code-free fallback) остава.


# ── news_aggregator + Tradier (нов модул + поправка) ──────────────────────
ENABLE_NEWS = os.getenv("ENABLE_NEWS", "1") == "1"
# Актуални RSS емисии (Reuters/CNBC смениха структурата си)
# ⚠ feeds.reuters.com и feeds.apnews.com са изоставени поддомейни (Reuters спря
# публичните RSS ~2020; AP feeds.* е мъртъв) → на GitHub runner-ите дават DNS
# resolution грешки. Remap-нати са към Google News RSS прокси (news.google.com
# resolve-ва навсякъде, връща валиден RSS XML с Reuters/AP заглавия за 24ч).
NEWS_RSS_FEEDS = {
    "Reuters Business": "https://news.google.com/rss/search?q=when:24h+allinurl:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "CNBC":             "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "Financial Times":  "https://www.ft.com/rss/home",
    "AP Business":      "https://news.google.com/rss/search?q=when:24h+allinurl:apnews.com&hl=en-US&gl=US&ceid=US:en",
}
# nitter е нестабилен — изключен по подразбиране (Поправка 4)
NEWS_ENABLE_NITTER = os.getenv("NEWS_ENABLE_NITTER", "0") == "1"
NITTER_HANDLES = ["unusual_whales", "zerohedge", "elerianm"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.poast.org"]
# Fallback: ако RSS върне нищо, scrape-ваме заглавия директно от тези страници (BeautifulSoup)
NEWS_SCRAPE_FALLBACK = {
    "Reuters":          "https://www.reuters.com/markets/",
    "CNBC":             "https://www.cnbc.com/world/?region=world",
    "AP Business":      "https://apnews.com/hub/business",
}

# ── Tradier (primary source за unusual options; Market Chameleon = fallback) ─
TRADIER_API_KEY = os.getenv("TRADIER_API_KEY", "")
TRADIER_BASE = os.getenv("TRADIER_BASE", "https://api.tradier.com/v1")

# Универс за Tradier unusual-options сканиране (option volume vs open interest).
# По-малък = по-бързо/по-малко API calls. Редактируем.
UNUSUAL_OPTIONS_UNIVERSE = [
    "NVDA", "AMD", "AAPL", "MSFT", "META", "GOOGL", "AMZN", "TSLA", "AVGO",
    "PLTR", "COIN", "MSTR", "SMCI", "MARA", "RIOT", "SOFI", "NIO", "BABA",
    "F", "BAC", "INTC", "MU", "CRM", "NFLX", "DIS",
]
UNUSUAL_OPTIONS_MIN_RATIO = float(os.getenv("UNUSUAL_OPTIONS_MIN_RATIO", 0.6))  # vol/OI праг

# NDX100 състав — СТАТИЧЕН списък, ръчно поддържан. Wikipedia премахна structured
# компонентната таблица от Nasdaq-100 статията (само външен линк към nasdaq.com
# остана) — вече не е скрейпваем източник. Обнови ръчно при промяна в индекса:
# отвори https://www.nasdaq.com/market-activity/quotes/Nasdaq-100-Index-Components,
# копирай тикърите. Снимка към 2026-07-10 (103 компонента, вкл. GOOG/GOOGL dual-class).
NDX100_STATIC_TICKERS = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "ALAB", "ALNY", "AMAT",
    "AMD", "AMGN", "AMZN", "APP", "ARM", "ASML", "AVGO", "AXON", "BKNG", "BKR",
    "CCEP", "CDNS", "CEG", "CMCSA", "COST", "CPRT", "CRWD", "CRWV", "CSCO", "CSX",
    "CTAS", "DASH", "DDOG", "DXCM", "EA", "EXC", "FANG", "FAST", "FER", "FTNT",
    "GEHC", "GILD", "GOOG", "GOOGL", "HON", "HONA", "IDXX", "INTC", "INTU", "ISRG",
    "KDP", "KHC", "KLAC", "LIN", "LITE", "LRCX", "MAR", "MCHP", "MDLZ", "MELI",
    "META", "MNST", "MPWR", "MRVL", "MSFT", "MSTR", "MU", "NBIS", "NFLX", "NVDA",
    "NXPI", "ODFL", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PLTR", "PYPL",
    "QCOM", "REGN", "RKLB", "ROP", "ROST", "SBUX", "SHOP", "SNDK", "SNPS", "SPCX",
    "STX", "TER", "TMUS", "TRI", "TSLA", "TTWO", "TXN", "VRTX", "WBD", "WDAY",
    "WDC", "WMT", "XEL",
]

# ── Splits филтри (Поправка 1) ────────────────────────────────────────────
SPLITS_MIN_PRICE = float(os.getenv("SPLITS_MIN_PRICE", 10))          # > $10
SPLITS_MIN_MARKET_CAP = float(os.getenv("SPLITS_MIN_MARKET_CAP", 500_000_000))  # > $500M

# ── Unusual options (Поправка 2): yfinance primary ────────────────────────
# Сканирането на опционни вериги е бавно — лимитираме броя тикъри на ден.
UNUSUAL_OPTIONS_SCAN_LIMIT = int(os.getenv("UNUSUAL_OPTIONS_SCAN_LIMIT", 60))

# ── SEC EDGAR 13F (Поправка 3): primary за Superinvestor Positions ─────────
# EDGAR изисква descriptive User-Agent с реален контакт — стойността се
# подава само през env var (GitHub Secret), никога не се комитва в кода.
EDGAR_UA = os.getenv("EDGAR_UA", "market-brief-bot (contact via GitHub repo)")
# CIK номера — верифицирани directamente през data.sec.gov/submissions
# (не по име само — вижте FIX бележките, две грешки хванати точно така).
# 16 мениджъра общо. Ключ = CIK (10 цифри, нулево-допълнен), стойност = име.
#
# FIX 2026-08-17: старият Klarman CIK (0001061219) сочеше към ENTERPRISE
# PRODUCTS PARTNERS L.P. — напълно различна компания, никога не е бил Baupost.
# Верен CIK: 0001061768 (BAUPOST GROUP LLC/MA).
#
# FIX 2026-08-17: Разширяване от 5 на 16 мениджъра. Първите по име съвпадения
# за Tepper/Appaloosa, Marks/Oaktree, Armitage/Egerton и Pabrai бяха ОТДАВНА
# НЕАКТИВНИ entity-та (фирмите преминават към нови SEC filing CIK-ове с
# годините — последен filing 2016/2011/2013/2012 съответно) — наложи се
# допълнително търсене за текущите активни filers. Pabrai's официална SEC
# filing entity се оказа "Dalal Street, LLC", не "Pabrai"/"Pabrai Investments".
DATAROMA_CIK = {
    "0001067983": "Уорън Бъфет · Berkshire Hathaway",
    "0001649339": "Майкъл Бъри · Scion Asset Management",  # filing_status="stopped" очаквано — фондът закрит 2025
    "0001336528": "Бил Акман · Pershing Square",
    "0001061768": "Сет Кларман · Baupost Group",
    "0001536411": "Стенли Дракенмилър · Duquesne Family Office",
    "0001167483": "Чейс Коулман · Tiger Global Management",
    "0001647251": "Крис Хон · TCI Fund Management",
    "0001040273": "Даниел Лоуб · Third Point",
    "0001656456": "Дейвид Тепър · Appaloosa Management",
    "0000949509": "Хауърд Маркс · Oaktree Capital Management",
    "0001581811": "Джон Армитидж · Egerton Capital",
    "0001709323": "Ли Лу · Himalaya Capital Management",
    "0001549575": "Мониш Пабрай · Dalal Street (Pabrai Investment Funds)",
    "0001061165": "Стивън Мандел · Lone Pine Capital",
    "0001569205": "Тери Смит · Fundsmith",
    "0001454502": "Triple Frond Partners",
}
# EDGAR-специфичен праг: позиция се брои за "увеличена" само ако бр. акции е
# нараснал с поне този % спрямо предходното тримесечие (сравнение по CUSIP).
# 5% отсява шума от дребни закръгления/технически корекции между подавания,
# без да губи реални акумулационни ходове.
DATAROMA_MIN_SHARE_INCREASE_PCT = float(os.getenv("DATAROMA_MIN_SHARE_INCREASE_PCT", 5.0))

# ── COT (Commitments of Traders) ──────────────────────────────────────────
ENABLE_COT = os.getenv("ENABLE_COT", "1") == "1"
COT_PERCENTILE_LOW = float(os.getenv("COT_PERCENTILE_LOW", 10))
COT_PERCENTILE_HIGH = float(os.getenv("COT_PERCENTILE_HIGH", 90))
COT_BATCH_SIZE = int(os.getenv("COT_BATCH_SIZE", 5))
COT_BATCH_MAX_TOKENS = int(os.getenv("COT_BATCH_MAX_TOKENS", 3000))
# FIX 2026-08-02: горна граница на running seen_tickers речника (soft cross-batch
# consistency, ai_brief.py: cot_theses) — FIFO, за да не расте prior_context
# неограничено на дни с много batch-ове/тикъри.
COT_SEEN_TICKERS_CAP = int(os.getenv("COT_SEEN_TICKERS_CAP", 20))
# ── MOVE Index (ICE BofA, bond volatility) ────────────────────────────────
MOVE_YELLOW_THRESHOLD = float(os.getenv("MOVE_YELLOW_THRESHOLD", 100))
MOVE_RED_THRESHOLD = float(os.getenv("MOVE_RED_THRESHOLD", 150))
MOVE_SPIKE_WEEKLY_DELTA = float(os.getenv("MOVE_SPIKE_WEEKLY_DELTA", 15))
# ── VIX Term Structure (VIX9D / VIX3M ratio) ──────────────────────────────
VIX_TERM_WARNING_THRESHOLD = float(os.getenv("VIX_TERM_WARNING_THRESHOLD", 1.0))
VIX_TERM_BACKWARDATION_THRESHOLD = float(os.getenv("VIX_TERM_BACKWARDATION_THRESHOLD", 1.1))
# Low-liquidity yfinance тикъри (^MOVE, ^VIX9D, ^VIX3M) понякога спират да
# публикуват нови данни за дни наред — над този праг стойността се третира
# като stale и индикаторът се крие (hide), вместо да показва остаряло число.
STALENESS_THRESHOLD_DAYS = int(os.getenv("STALENESS_THRESHOLD_DAYS", 3))
# FIX 2026-08-18: fed_net_liquidity() (macro_layer.py) имаше само "series
# напълно празна" защита, НЕ staleness проверка — потвърдено 2 последователни
# дни с идентична стойност ($5795.8 млрд), диагностицирано като легитимно
# (WALCL/WTREGEN — Fed H.4.1 отчет — реално са седмични, RRP в момента е
# нищожно малка ($<1 млрд), не мести закръгленото число), но структурно
# липсваше _is_stale()-стил guard, same дупка каквато имаше MOVE/VIX преди
# 2026-07-15. STALENESS_THRESHOLD_DAYS (3 дни) е калибриран за ДНЕВНИ VIX/MOVE
# серии — директно преизползване тук би флагвало WALCL/WTREGEN като "stale"
# през половината от всяка нормална седмица. Отделен, по-дълъг праг:
# нормален седмичен цикъл (7 дни) + buffer за публикационно забавяне
# (H.4.1 обикновено излиза четвъртък следобед за предходната сряда — 1-2 дни
# закъснение вече е нормално, не стрес сигнал; ~5 дни допълнителен buffer над
# това покрива и празнични отмествания).
FED_LIQUIDITY_STALENESS_DAYS = int(os.getenv("FED_LIQUIDITY_STALENESS_DAYS", 12))
# RRPONTSYD е ДНЕВНА (работни дни) компонента — same клас серия като VIX/MOVE
# (публикува се всеки работен ден), затова reuse-ва STALENESS_THRESHOLD_DAYS
# директно, не нужна отделна константа.

# ── Market Breadth (% над 40dMA) — 9-ти термометър индикатор ──────────────
# Feasibility проверка 2026-08-15: чист безплатен T2108 feed НЕ съществува
# (нито през yfinance — ^T2108/^NYSI/^NYMO/^NYAD всички 404, нито през друг
# безплатен API — T2108 е proprietary на TC2000/Worden). Собствено изчислено
# приближение върху screener.build_universe() (S&P500+Nasdaq100+MidCap400) —
# ВАЖНО: това НЕ е буквален NYSE T2108 (различен, по-широк/Nasdaq-тежък
# universe), затова навсякъде в кода/UI-а името е explicit "Market Breadth
# (% над 40dMA)", никога "T2108". Empирично тествано: 903 тикъра, 38s, 0
# грешки, 0 rate limiting (виж experiments discussion 2026-08-15).
# Mean-reverting zoни: 20-80% = здравословно,
# >80% = overbought, 10-20% = приближава капитулация, <10% = механично "red"
# за термометъра, НО contrarian-bullish текстов тон (историческа bottoming
# зона), не паника.
ENABLE_MARKET_BREADTH = os.getenv("ENABLE_MARKET_BREADTH", "1") == "1"
BREADTH_BATCH_SIZE = int(os.getenv("BREADTH_BATCH_SIZE", 50))
BREADTH_MIN_VALID_TICKERS = int(os.getenv("BREADTH_MIN_VALID_TICKERS", 200))  # sanity floor преди да се доверим на %-а
BREADTH_OVERBOUGHT_THRESHOLD = float(os.getenv("BREADTH_OVERBOUGHT_THRESHOLD", 80.0))
BREADTH_HEALTHY_LOW = float(os.getenv("BREADTH_HEALTHY_LOW", 20.0))
BREADTH_CAPITULATION_THRESHOLD = float(os.getenv("BREADTH_CAPITULATION_THRESHOLD", 10.0))

# ── SEC Form 4 Insider Buying (officers CEO/CFO/President/COO, open market) ──
ENABLE_INSIDER_BUYING = os.getenv("ENABLE_INSIDER_BUYING", "1") == "1"
INSIDER_MIN_VALUE = float(os.getenv("INSIDER_MIN_VALUE", 100_000))
INSIDER_CLUSTER_WINDOW_DAYS = int(os.getenv("INSIDER_CLUSTER_WINDOW_DAYS", 14))
INSIDER_CLUSTER_MIN_COUNT = int(os.getenv("INSIDER_CLUSTER_MIN_COUNT", 3))

# ── Корелационен риск между Action кандидати (pairwise Pearson) ───────────
ENABLE_CORRELATION_CHECK = os.getenv("ENABLE_CORRELATION_CHECK", "1") == "1"
CORRELATION_LOOKBACK_DAYS = int(os.getenv("CORRELATION_LOOKBACK_DAYS", 60))
CORRELATION_THRESHOLD = float(os.getenv("CORRELATION_THRESHOLD", 0.75))

# ── Entry Timing (screening ≠ timing — виж entry_timing.py docstring-а) ────
# Концепции 1+2 (pivot+volume confirmation, extension rule) — чисто
# информационен badge на Action картата, НЕ пипа CANSLIM screening/apply_
# hard_rules логиката. Концепция 3 (distribution days market gate) е отделна,
# по-късна задача — не участва тук.
ENABLE_ENTRY_TIMING = os.getenv("ENABLE_ENTRY_TIMING", "1") == "1"
# По-строг праг от screener.py's MAX_PCT_BELOW_PIVOT/+5% extended cutoff —
# 0-2% над pivot = идеална входна зона; 2-5% е все още валиден CANSLIM setup
# (screener.py вече го допуска), но Entry Timing го флагва като "extended,
# изчакай pullback" вместо мълчаливо да го третира като идентично добър вход.
ENTRY_TIMING_EXTENDED_PCT = float(os.getenv("ENTRY_TIMING_EXTENDED_PCT", 2.0))
# Концепция 3 — distribution days market gate. IBD/O'Neil стандартна дефиниция:
# close надолу с поне този % спрямо предходния close, И обем над предходния
# обем (не просто close<prev без магнитуден праг — иначе тривиални -0.01%
# тикове се броят наравно с -2% срив дни).
DISTRIBUTION_DAYS_LOOKBACK = int(os.getenv("DISTRIBUTION_DAYS_LOOKBACK", 25))
DISTRIBUTION_DAYS_MIN_DECLINE_PCT = float(os.getenv("DISTRIBUTION_DAYS_MIN_DECLINE_PCT", 0.2))
# FIX калибрация: класическите O'Neil прагове ("3-4 = внимание", "5+ = риск")
# НЕ пасват на реални данни — проверено на 3г SPY история (IBD дефиниция):
# 50-ти персентил е ВЕЧЕ 5 (модерните пазари имат структурно по-висока базова
# честота на "down+higher-vol" дни, отколкото когато O'Neil е калибрирал
# правилото десетилетия по-рано) — "5+" би флагвало "риск" ~50% от времето,
# безполезен сигнал. Прагове тук са на 70-ти/95-ти персентил от реалната
# история (7 / 9), не текстовите O'Neil числа. Forward-return корелация е
# практически нулева (0.011), но std на 10-дневен forward return расте
# отчетливо с broя (1.96→2.37→3.20→5.12 по bucket) — метриката предсказва
# НЕСИГУРНОСТ/риск, не посока, точно каквото Entry Timing търси.
DISTRIBUTION_DAYS_YELLOW = int(os.getenv("DISTRIBUTION_DAYS_YELLOW", 7))
DISTRIBUTION_DAYS_RED = int(os.getenv("DISTRIBUTION_DAYS_RED", 9))

# ── Track Record / Backtest (Action препоръки: target/stop резолюция) ─────
ENABLE_BACKTEST = os.getenv("ENABLE_BACKTEST", "1") == "1"
BACKTEST_MAX_HOLD_WEEKS = int(os.getenv("BACKTEST_MAX_HOLD_WEEKS", 16))

# ── GLB (Green Line Breakout) — Classic/Momentum ATH пробив скрийнър ──────
# Вдъхновено от Eric Wish (wishingwealthblog.com) методологията, ПРЕРАБОТЕНО
# след backtest диагностика (experiments/glb_backtest.py,
# experiments/glb_monthly_check.py, 2026-08-12/13): буквалният месечен
# duration-only критерий ("all-time high not penetrated for 3 straight
# months") се генерализира на всичките 4 тествани тикъра (SNDK/WDC/MU/STX).
# Дневен tightness overlay (band_hold_pct) е независимо потвърден от
# WDC/STX/MU историческите multi-month бази, НО системно пропуска
# explosive/momentum пробиви — включително WDC's собствен 2025 breakout,
# ВЪПРЕКИ 47г история. Затова Classic/Momentum разграничението е ПО SETUP
# (дали overlay-ът минава на конкретния breakout момент), НЕ по възрастта на
# тикъра — age-based gating би направил WDC-стил зрели-компании-с-momentum-
# пробив сетъпи невидими за модула.
# ИЗВЕСТНО ОГРАНИЧЕНИЕ (2026-08-14): universe-ът тук е screener.build_
# universe() — S&P500 + Nasdaq-100 + S&P MidCap 400. Established, ликвидни
# компании; НЕ включва скорошни spinoff/малки IPO имена като SNDK (spin-off
# от WDC, февруари 2025 — извън и трите Wikipedia списъка). Модулът работи
# коректно за established компании (validirano: 903 тикъра, 71s, 0 грешки,
# 15 classic + 9 momentum кандидата) — но НЯМА да хване точно "explosive
# spinoff/recent-IPO" сценария, който първоначално мотивира изграждането му
# (виж experiments/glb_backtest.py history). Разширяване на universe-а
# (напр. отделен recent-IPO/spinoff списък) е отделна бъдеща задача, не
# част от текущия обхват.
ENABLE_GLB_SCREENER = os.getenv("ENABLE_GLB_SCREENER", "1") == "1"
GLB_HISTORY_PERIOD = os.getenv("GLB_HISTORY_PERIOD", "max")  # yfinance period — 2y (screener.py) е недостатъчен за multi-decade ATH
GLB_MIN_MONTHS_UNPENETRATED = int(os.getenv("GLB_MIN_MONTHS_UNPENETRATED", 3))  # буквален Wish праг, универсален гейт
GLB_MIN_ATH_HISTORY_YEARS = float(os.getenv("GLB_MIN_ATH_HISTORY_YEARS", 3.0))  # data-quality label (ath_label), НЕ Classic/Momentum gate
GLB_APPROACH_PCT = float(os.getenv("GLB_APPROACH_PCT", 15.0))                  # tightness overlay: "в рамките на X% от prior_high"
GLB_MIN_CONSOLIDATION_DAYS = int(os.getenv("GLB_MIN_CONSOLIDATION_DAYS", 63))  # trailing прозорец за overlay-а (~3 месеца в търг. дни)
GLB_MIN_BAND_HOLD_PCT = float(os.getenv("GLB_MIN_BAND_HOLD_PCT", 85.0))        # overlay праг -> "classic" upgrade


# ══════════════════════════════════════════════════════════════════════════
# v2.1 · Поправки 2026-07-15 (виж FIXES_2026-07-15.md)
# ══════════════════════════════════════════════════════════════════════════
# Magic Formula "value confirmed": кандидат получава MF✓ ако комбинираният му
# Greenblatt ранг попада в топ дециала на (референтен универс + кандидати).
MF_CONFIRM_DECILE = float(os.getenv("MF_CONFIRM_DECILE", 0.10))
# ATM IV под този праг (%) = боклук от застояли котировки → отхвърля се.
IV_SANITY_MIN_PCT = float(os.getenv("IV_SANITY_MIN_PCT", 5.0))
# FIX 2026-08-02: ATM контракт с lastTradeDate по-стар от толкова дни се третира
# като застоял/нетъргуван → IV-то му се отхвърля. Обратна посока на
# IV_SANITY_MIN_PCT — там хващаме абсурдно НИСКИ, тук абсурдно ВИСОКИ IV
# артефакти от мъртви контракти. Калибровано на реални данни (потвърдено 02.08.2026):
# ONB PUT (OI=1) последно търгуван преди 179 дни → IV 133.9% solver artifact,
# докато 6 реални ликвидни candidate тикъра (GRMN/NTRS/JPM/BAC/AIZ/DINO) бяха
# всички търгувани в рамките на ≤16 дни — чиста разделителна линия. bid/ask
# СПРЕД беше първоначален (грешен) избор за прага — GRMN PUT имаше 118% спред
# при вчерашна активна търговия (vol=22, OI=20), спредът не разграничава
# надеждно, старостта на сделката — да.
IV_MAX_QUOTE_AGE_DAYS = int(os.getenv("IV_MAX_QUOTE_AGE_DAYS", 30))
# Минимален общ опционен обем (puts+calls), за да е смислен P/C ratio.
PC_MIN_TOTAL_VOLUME = int(os.getenv("PC_MIN_TOTAL_VOLUME", 500))
# Минимум дни IV история за категорична IVR-базирана опционна препоръка.
IVR_MIN_DAYS_FOR_STRATEGY = int(os.getenv("IVR_MIN_DAYS_FOR_STRATEGY", 60))

# ── Earnings Season Recap (Case 1: Action картата, Case 2: track record) ──
# FIX 2026-08-13: единен recency праг за ДВАТА UI пътя (преди: entry_date
# филтър за Case 2 — премахнат, вече излишен, виж дискусията). recap изчезва
# изцяло (не само визуално) след толкова дни от последния отчет.
EARNINGS_RECAP_RECENCY_DAYS = int(os.getenv("EARNINGS_RECAP_RECENCY_DAYS", 10))
# Толеранс (в дни) при търсене на YoY реда — най-близкият отчет до "текуща
# дата - 365 дни", НЕ фиксирана позиция "N реда назад" (фискалните календари
# могат да се разминават между компании).
EARNINGS_YOY_TOLERANCE_DAYS = int(os.getenv("EARNINGS_YOY_TOLERANCE_DAYS", 60))
