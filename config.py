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
TRADIER_API_KEY = os.getenv("TRADIER_API_KEY", "")  # optional, options data

# ── Имейл доставка ────────────────────────────────────────────────────────
EMAIL_METHOD = os.getenv("EMAIL_METHOD", "smtp")    # "smtp" | "sendgrid"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://USERNAME.github.io/ai-investment-brief/")

# ── Claude модел ──────────────────────────────────────────────────────────
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

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
