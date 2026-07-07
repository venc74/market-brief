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
AI_BATCH_MAX_TOKENS = int(os.getenv("AI_BATCH_MAX_TOKENS", 4000))  # budget на batch

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

# ── 6. NAAIM исторически прозорец ─────────────────────────────────────────
NAAIM_HISTORY_WEEKS = int(os.getenv("NAAIM_HISTORY_WEEKS", 52))

# ── Toggle-и за новите скрейпъри (за лесно изключване при проблем) ─────────
ENABLE_MAGIC_FORMULA = os.getenv("ENABLE_MAGIC_FORMULA", "1") == "1"
ENABLE_BORROW_DATA = os.getenv("ENABLE_BORROW_DATA", "1") == "1"
ENABLE_UNUSUAL_OPTIONS = os.getenv("ENABLE_UNUSUAL_OPTIONS", "1") == "1"
ENABLE_SPLITS_CALENDAR = os.getenv("ENABLE_SPLITS_CALENDAR", "1") == "1"


# ── Dataroma · Superinvestor Moves ────────────────────────────────────────
# Минимална стойност на позицията, за да се брои „значима" покупка.
DATAROMA_MIN_VALUE = float(os.getenv("DATAROMA_MIN_VALUE", 10_000_000))   # $10M
# Ако True: при fallback към allact.php (без стойности) се отхвърлят редовете
# без известна стойност. По подразбиране False — по-добре да видиш хода.
DATAROMA_STRICT_VALUE = os.getenv("DATAROMA_STRICT_VALUE", "0") == "1"
ENABLE_DATAROMA = os.getenv("ENABLE_DATAROMA", "1") == "1"
# Кодове на superinvestors от URL-а на dataroma (/m/holdings.php?m=КОД).
# ⚠ ВЕРИФИЦИРАЙ ги на сайта — при грешен код мениджърът тихо се пропуска.
# Редактируем: добавяй/махай свободно. Ключ = код, стойност = четимо име.
DATAROMA_MANAGERS = {
    "BRK":      "Уорън Бъфет · Berkshire Hathaway",
    "SAM":      "Майкъл Бъри · Scion Asset Management",
    "DFO":      "Стенли Дракенмилър · Duquesne Family Office",
    "psc":      "Бил Акман · Pershing Square",
    "BAUPOST":  "Сет Кларман · Baupost Group",
    "GR":       "Дейвид Айнхорн · Greenlight Capital",
    "AKRE":     "Чък Акре · Akre Capital",
    "AM":       "Дейвид Тепър · Appaloosa",
}


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
# CIK номера на топ мениджърите (подадени от теб). Ключ = CIK, стойност = име.
DATAROMA_CIK = {
    "0001067983": "Уорън Бъфет · Berkshire Hathaway",
    "0001649339": "Майкъл Бъри · Scion Asset Management",
    "0001336528": "Бил Акман · Pershing Square",
    "0001061219": "Сет Кларман · Baupost Group",
    "0001536411": "Стенли Дракенмилър · Duquesne Family Office",
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
# ── MOVE Index (ICE BofA, bond volatility) ────────────────────────────────
MOVE_YELLOW_THRESHOLD = float(os.getenv("MOVE_YELLOW_THRESHOLD", 100))
MOVE_RED_THRESHOLD = float(os.getenv("MOVE_RED_THRESHOLD", 150))
MOVE_SPIKE_WEEKLY_DELTA = float(os.getenv("MOVE_SPIKE_WEEKLY_DELTA", 15))
# ── VIX Term Structure (VIX9D / VIX3M ratio) ──────────────────────────────
VIX_TERM_WARNING_THRESHOLD = float(os.getenv("VIX_TERM_WARNING_THRESHOLD", 1.0))
VIX_TERM_BACKWARDATION_THRESHOLD = float(os.getenv("VIX_TERM_BACKWARDATION_THRESHOLD", 1.1))

# ── SEC Form 4 Insider Buying (officers CEO/CFO/President/COO, open market) ──
ENABLE_INSIDER_BUYING = os.getenv("ENABLE_INSIDER_BUYING", "1") == "1"
INSIDER_MIN_VALUE = float(os.getenv("INSIDER_MIN_VALUE", 100_000))
INSIDER_CLUSTER_WINDOW_DAYS = int(os.getenv("INSIDER_CLUSTER_WINDOW_DAYS", 14))
INSIDER_CLUSTER_MIN_COUNT = int(os.getenv("INSIDER_CLUSTER_MIN_COUNT", 3))

# ── Корелационен риск между Action кандидати (pairwise Pearson) ───────────
ENABLE_CORRELATION_CHECK = os.getenv("ENABLE_CORRELATION_CHECK", "1") == "1"
CORRELATION_LOOKBACK_DAYS = int(os.getenv("CORRELATION_LOOKBACK_DAYS", 60))
CORRELATION_THRESHOLD = float(os.getenv("CORRELATION_THRESHOLD", 0.75))

# ── Track Record / Backtest (Action препоръки: target/stop резолюция) ─────
ENABLE_BACKTEST = os.getenv("ENABLE_BACKTEST", "1") == "1"
BACKTEST_MAX_HOLD_WEEKS = int(os.getenv("BACKTEST_MAX_HOLD_WEEKS", 16))
# Ако тикър вече има отворена (open/trailing) позиция от последните N дни,
# нов Action сигнал за него се третира като продължение, не нова сделка.
BACKTEST_DEDUP_WINDOW_DAYS = int(os.getenv("BACKTEST_DEDUP_WINDOW_DAYS", 10))
