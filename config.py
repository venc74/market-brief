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
# FIX 2026-09-12 (findings log 04-11.09, т.2): "regime_gate" watchlist
# кандидати (чакат конкретна смяна на пазарния режим + цена/обем условие)
# по-рано разчитаха на AI-измислена calendar дата в свободен текст —
# потвърдено на 4 дни (DELL/ROKU): AI-то преждевременно твърдеше правилото
# вече е задействало (8 дни преди собствената си дата), после напълно
# забравяше концепцията на следващия ден. Нула code state зад нея.
# WATCHLIST_STALENESS_DAYS вече е code-computed прозорец (src/watchlist_
# expiry.py), не AI избор. 10 работни дни (~2 календарни седмици) — разумен
# "watchlist review цикъл" здрав разум старт (не backtested): достатъчно
# дълъг да даде честен шанс на regime промяна да се случи, достатъчно
# кратък pivot/price нивата, изчислени спрямо конкретна историческа база,
# да не остареят прекалено. Tunable.
WATCHLIST_STALENESS_DAYS = int(os.getenv("WATCHLIST_STALENESS_DAYS", 10))
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

# ── Pivot / buyable zone / buy-stop (пакет 1, т.1 и т.2 — 2026-10-02) ─────
# pivot = най-високият High на базата БЕЗ последните PIVOT_EXCLUDE_LAST_BARS
# бара. Дотук беше max(High[-65:]), т.е. включваше сигналния бар → close <= pivot
# ВИНАГИ: 95 от 97 Action реда с pct_from_pivot < 0, 2 точно 0, проверката за
# "extended" беше мъртъв код, Entry Timing "good" — невъзможен (14 "wait", 0 "good").
# Реплей 02.01.2024 → 02.10.2026 (904 тикъра, технически слой, обем ≥1.4×,
# хоризонт 20 дни): N=0 → 0 пробива по дефиниция; N=1…15 дава плоска очаквана
# стойност (R 0.03–0.13, win 49–51%) — няма оптимум по данни, 5 = една търговска
# седмица.
PIVOT_BASE_BARS = 65                                    # 13 седмици (както досега)
PIVOT_EXCLUDE_LAST_BARS = int(os.getenv("PIVOT_EXCLUDE_LAST_BARS", 5))
# Buyable zone: close до +5% над pivot. Над това = "extended" (не се гони).
BUYABLE_ZONE_MAX_PCT = float(os.getenv("BUYABLE_ZONE_MAX_PCT", 5.0))
# buy-stop прозорец: брой търговски сесии, ВКЛЮЧИТЕЛНО сесията на брифа, в които
# High >= pivot активира входа (реплей 02.01.2024 → 02.10.2026, 2464 buy-stop
# сигнала под pivot: 36% се активират на сесия +1, 63% до сесия +5).
BUY_STOP_WINDOW_SESSIONS = int(os.getenv("BUY_STOP_WINDOW_SESSIONS", 5))
# NYSE празници 2026–2027 за показваната дата "валиден до". 2026 е проверен срещу
# дневните барове на SPY (точно тези 8 работни дни липсват до 02.10.2026); 2027 и
# остатъкът от 2026 — по официалния календар на NYSE (наблюдавани празници).
NYSE_HOLIDAYS = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
})

# ── Стоп (пакет 1, т.3 — 2026-10-03) ──────────────────────────────────────
# Структурен стоп = най-ниският Low на последните STOP_STRUCT_LOOKBACK_BARS бара
# (сигналният бар е включен), минус STOP_STRUCT_BUFFER_PCT% буфер — точно както в
# реплея (W=15, ×0.99). Стопът никога не е по-далеч от STOP_MAX_PCT% под входа;
# ако СТРУКТУРНИЯТ риск надхвърля STOP_REJECT_STRUCT_RISK_PCT%, кандидатът не е
# Action (Watchlist, "твърде разтегнато"). Преди: max(под базата −2%, под 50DMA −1%) —
# 13-седмична база е твърде далеч за стоп (реплей, стопове: медианен риск 11%).
# Реплей 02.01.2024 → 02.10.2026 (v2, обем ≥1.4×, хоризонт 20 дни; прозорец → сигнали,
# win, среден R): 5 бара → 1156, 45%, 0.01; 10 → 813, 49%, 0.04; 15 → 565, 55%, 0.13;
# 20 → 369, 57%, 0.13. По-големият прозорец реже и кандидатите (риск >10%), т.е. част
# от по-високия win rate е селекция, не по-добър стоп; няма демонстрирана алфа.
STOP_STRUCT_LOOKBACK_BARS = int(os.getenv("STOP_STRUCT_LOOKBACK_BARS", 15))
STOP_STRUCT_BUFFER_PCT = float(os.getenv("STOP_STRUCT_BUFFER_PCT", 1.0))
STOP_MAX_PCT = float(os.getenv("STOP_MAX_PCT", 8.0))
STOP_REJECT_STRUCT_RISK_PCT = float(os.getenv("STOP_REJECT_STRUCT_RISK_PCT", 10.0))

# ── Цел (пакет 1, т.4 — 2026-10-03) ───────────────────────────────────────
# Цел 1 = MIN_REWARD_RISK (2R). На нея се продава TARGET_PARTIAL_FRACTION от позицията;
# остатъкът се пази с trailing — излиза при Close под TRAIL_SMA_DAYS-дневната средна, а
# първоначалният стоп остава активен. Преди: цялата позиция минаваше в trailing на цел 1
# и стопът се изключваше. Реплей: цел 2R / 3R / +20% / +25% дават статистически същия
# резултат (win 49%, R 0.04–0.06 при хоризонт 20 дни) — няма оптимум по данни; частичната
# продажба е решение за управление на риска, не за доходност.
TARGET_PARTIAL_FRACTION = float(os.getenv("TARGET_PARTIAL_FRACTION", 0.5))
TRAIL_SMA_DAYS = int(os.getenv("TRAIL_SMA_DAYS", 10))

# ── Minervini trend template + RS rating (пакет 1, т.9 — 2026-10-03) ─────
# Задължителен филтър за Action И Watchlist, слят със съществуващата Weinstein Stage 2
# проверка (screener.trend_template_checks — Stage 2 е първата част на шаблона, не
# отделен филтър): цена > 150DMA и 200DMA; 150DMA > 200DMA; 200DMA расте поне
# TT_MA200_RISING_BARS сесии (~1 месец); 50DMA > 150DMA и 200DMA; цена > 50DMA; цена
# поне TT_MIN_ABOVE_52W_LOW_PCT% над 52-седмичното дъно и най-много
# TT_MAX_BELOW_52W_HIGH_PCT% под 52-седмичния връх (252 сесии, High/Low).
# RS rating = перцентил (1–100) на претеглената доходност — 40% последното тримесечие
# + по 20% за всяко от трите преди него (тримесечие = RS_QUARTER_BARS сесии) — в ЦЕЛИЯ
# универс (всички с история, не само оцелелите); минимум RS_RATING_MIN. При по-малко от
# RS_RATING_MIN_UNIVERSE тикъра с данни (счупени batch-ове) рейтингът не се смята и
# филтърът се пропуска с предупреждение, вместо да реже на произволна извадка.
# TREND_TEMPLATE_ENABLED=0 връща само старата Stage 2 проверка (рейтингът остава за показване).
# Реплей 02.01.2024 → 01.10.2026 (904 тикъра, 690 сигнални дни, v2 с финалните параметри —
# обем ≥1.5×, 15-баров стоп, buy-stop 5 сесии, 50% на 2R, гап изход, MTM изтичане; векторизираният
# шаблон/рейтинг съвпада със screener.py на 1800/4465 проверени точки, trade_sim — със симулатора на
# реплея на всички 497 сигнала): БЕЗ т.9 → 61.4 технически оцелели на ден, 497 сигнала (0.72/ден, на
# 35% от дните), хоризонт 20 дни: win 57%, среден R +0.15, α спрямо SPY 0.0%; С т.9 → 54.1 на ден,
# 432 сигнала (0.63/ден, 32% от дните), win 59%, R +0.19, α +0.3%. Филтърът маха ~13% от сигналите;
# разликата в резултата е в рамките на шума (±0.08R) — не е демонстрирано подобрение, а по-чист пул.
TREND_TEMPLATE_ENABLED = os.getenv("TREND_TEMPLATE_ENABLED", "1") == "1"
TT_MA200_RISING_BARS = int(os.getenv("TT_MA200_RISING_BARS", 21))
TT_MIN_ABOVE_52W_LOW_PCT = float(os.getenv("TT_MIN_ABOVE_52W_LOW_PCT", 30.0))
TT_MAX_BELOW_52W_HIGH_PCT = float(os.getenv("TT_MAX_BELOW_52W_HIGH_PCT", 25.0))
RS_RATING_MIN = float(os.getenv("RS_RATING_MIN", 70))
RS_RATING_WEIGHTS = (0.4, 0.2, 0.2, 0.2)          # [последно тримесечие, 3–6м, 6–9м, 9–12м]
RS_QUARTER_BARS = 63
RS_RATING_MIN_UNIVERSE = int(os.getenv("RS_RATING_MIN_UNIVERSE", 150))

# ── Track Record v2: чист старт (пакет 1, т.7 — 2026-10-03) ───────────────
# При първия run с v2 кодът архивира v1 записите (data/backtest_archive_v1.json — НЕ се трият),
# затваря отворените v1 позиции по последния Close като "v1_closed" (mark-to-market R) и започва
# Track Record от нула; брифът показва един ред "v1 методология: n=…, win rate …, среден R …".
# OPEN✓, RE-ENTRY и позициите в COT промпта гледат само v2 записи. Превключването е еднократно
# и идемпотентно (data/track_record_state.json) и се връща с tracker_switch.revert_to_v1().
# TRACK_RECORD_V2=0 спира автоматичното превключване (v2 плановете пак се записват като v2).
TRACK_RECORD_V2 = os.getenv("TRACK_RECORD_V2", "1") == "1"

# ── Track Record: buy-stop кандидати (пакет 1б — 05.10.2026) ──────────────
# Watchlist картите с buy-stop (setup.kind == "below_pivot", валиден plan_preview) се следят като ОТДЕЛНА, независима книга ("buystop") в същия
# tracker — със същия модел на изпълнение като Action (trade_sim: вход при High ≥ buy-stop в прозорец от BUY_STOP_WINDOW_SESSIONS сесии, по
# max(Open, buy-stop), не над таван +5%; стоп/цел от картата). Записва се във ВСИЧКИ режими, с таг на режима. Не е препоръка и не е позиция:
# четците на позиции (OPEN✓, RE-ENTRY, COT, обобщението на Action) я игнорират. Реплей 02.01.2024–01.10.2026: без демонстрирана алфа.
TRACK_BUYSTOP = os.getenv("TRACK_BUYSTOP", "1") == "1"
# Чист старт: карти от дни ПРЕДИ тази дата не се записват (нито от snapshot-ите, нито от днешния Watchlist) — иначе първото пускане на 1б би
# записало ретроактивно картите от вторник (след качването на пакет 2 те вече носят plan_preview). Деня след качването на 1б (сряда
# 07.10.2026 — първият бриф с новия код) се записва от тогава нататък; ако качването се премести — сменя се тази дата. Празен низ изключва guard-а.
BUYSTOP_TRACK_FROM = os.getenv("BUYSTOP_TRACK_FROM", "2026-10-07")
# Win rate, медиана, сравнение със SPY и разбивка по режим на buy-stop книгата се показват чак при поне толкова ЗАТВОРЕНИ записа; дотогава —
# само броят и средният R (при n=14 доверителният интервал на win rate е ~±25 пункта — реплеят на реалните кандидати: 1 печеливш от 14).
BUYSTOP_MIN_CLOSED_FOR_WINRATE = int(os.getenv("BUYSTOP_MIN_CLOSED_FOR_WINRATE", 20))

# ── Предупреждение за отчет върху картата (пакет 4б т.д — 06.10.2026) ──────
# При отчет в следващите EARNINGS_WARNING_SESSIONS търговски сесии картата показва датата и ОЧАКВАНОТО движение от опциите (само информация, без промяна на размера).
# Очакваното движение = ATM straddle на първия падеж СЛЕД отчета, от който е извадена базовата волатилност (straddle на последния падеж ПРЕДИ отчета, мащабиран
# по корен от броя сесии): събитие = sqrt(A² − B²·Ta/Tb) / цена. Реален пример (FTNT, отчет 28.10, опции от 05.10): простият straddle на 30.10 е ±13.9%
# (включва 25 дни базова волатилност), а само събитието е ±10.6%. Данните са от следобедната снимка (bid/ask в сесията); ненадеждно → само датата.
EARNINGS_WARNING_SESSIONS = int(os.getenv("EARNINGS_WARNING_SESSIONS", 20))
EARNINGS_SNAPSHOT_WINDOW_DAYS = int(os.getenv("EARNINGS_SNAPSHOT_WINDOW_DAYS", 32))      # календарни дни напред (20 сесии ≈ 28 дни + резерв) за кои отчети се снимат straddle-и
EARNINGS_MOVE_MAX_EXPIRY_GAP_DAYS = int(os.getenv("EARNINGS_MOVE_MAX_EXPIRY_GAP_DAYS", 7))   # падежът след отчета най-много толкова дни след него
EARNINGS_MOVE_MAX_BASELINE_GAP_DAYS = int(os.getenv("EARNINGS_MOVE_MAX_BASELINE_GAP_DAYS", 21))  # падежите преди и след отчета са най-много толкова дни един от друг
EARNINGS_MOVE_MIN_BASELINE_SESSIONS = int(os.getenv("EARNINGS_MOVE_MIN_BASELINE_SESSIONS", 3))  # падежът преди отчета е поне толкова сесии след снимката
EARNINGS_MOVE_MAX_SPREAD_PCT = float(os.getenv("EARNINGS_MOVE_MAX_SPREAD_PCT", 25.0))     # bid/ask спред на всяко краче (% от mid)
EARNINGS_MOVE_MAX_STRIKE_DIST_PCT = float(os.getenv("EARNINGS_MOVE_MAX_STRIKE_DIST_PCT", 3.0))  # ATM страйкът е най-много толкова % от цената
EARNINGS_MOVE_MIN_PCT, EARNINGS_MOVE_MAX_PCT = 0.3, 60.0                                  # правдоподобност на резултата

# ── Qullamaggie сетъпи (отделна стратегия — измерване, не препоръка; 06.10.2026) ──────────────────────────────────────────────
# Първоизточници на правилата (qullamaggie.com): https://qullamaggie.com/my-3-timeless-setups-that-have-made-me-tens-of-millions/ ,
# https://qullamaggie.com/how-to-master-a-setup-episodic-pivots/ , https://qullamaggie.com/faq/ (формулата на ADR). Какво е негово и какво е мое — в DESIGN.md на проучването
# (scratchpad/qm) и в CLAUDE.md. Универсът е същият като на скрийнъра (без малки акции).
ENABLE_QM = os.getenv("ENABLE_QM", "1") == "1"
# Breakout скенер (src/qm_breakout.py) — "отпуснатата конфигурация" на реплея (02.2024–10.2026, 904 тикъра), но с лидери топ 10%
QM_LEAD_PCT = float(os.getenv("QM_LEAD_PCT", 0.90))              # най-добрият перцентил по ръст за 1, 3 и 6 месеца (негово: топ 1–2% от ~7000 ≈ топ 10% от наш универс от ~900)
QM_RUN_MIN = float(os.getenv("QM_RUN_MIN", 0.20))                # предходен ръст до пика ≥ +20% (негово: 30–100%+; в реплея махането му не променя резултата)
QM_RUN_LOOKBACK_BARS, QM_PEAK_WINDOW_BARS = 40, 62               # низ преди пика / прозорец за пика (≈1–3 месеца)
QM_BASE_MIN_BARS, QM_BASE_MAX_BARS = 8, 45                       # консолидация ≈ 2 седмици – 2 месеца (негово)
QM_DEPTH_MAX = float(os.getenv("QM_DEPTH_MAX", 0.30))            # пулбек от пика най-много 30% (мое: "организиран")
QM_HIGHER_LOW_TOL = 0.005                                        # higher lows: low на последните 5 бара ≥ low на предишните 5 (допуск 0.5%)
QM_TIGHT_MAX = float(os.getenv("QM_TIGHT_MAX", 1.2))             # среден дневен диапазон на последните 5 бара ≤ 1.2× ADR (отпуснато); служи и за подредба — по-малко = по-стегнато
QM_VOL_DRY = float(os.getenv("QM_VOL_DRY", 1.1))                 # среден обем на последните 5 бара ≤ 1.1× 50-дневния (спадащ обем в базата)
QM_NEAR_ADR = float(os.getenv("QM_NEAR_ADR", 2.0))               # нивото на пробива е най-много 2× ADR над затварянето
QM_TRIGGER_BARS = 10                                             # ниво на пробив = най-високият High на последните 10 сесии (върхът на флага)
QM_ADR_MIN = float(os.getenv("QM_ADR_MIN", 3.0))                 # ADR20 ≥ 3% (негово е само "стопът ≤ ADR"; минималният ADR е мой)
QM_DOLLAR_VOLUME_MIN = float(os.getenv("QM_DOLLAR_VOLUME_MIN", 10_000_000))   # среден 20-дневен долар обем (мое; универсът е >$60M)
QM_PRICE_MIN = float(os.getenv("QM_PRICE_MIN", 5.0))
QM_MAX_CARDS = int(os.getenv("QM_MAX_CARDS", 8))                 # най-много карти, подредени по стягане на базата
QM_EXPECTED_STOP_ADR = float(os.getenv("QM_EXPECTED_STOP_ADR", 0.55))   # очакван стоп = ниво − 0.55×ADR (медианата на (вход − low на деня) в реплея; интерквартилно 0.41–0.71)
QM_MAX_STOP_ADR = float(os.getenv("QM_MAX_STOP_ADR", 1.0))      # негово: стопът не по-широк от ADR
QM_RISK_FACTOR = float(os.getenv("QM_RISK_FACTOR", 0.5))         # размер на позицията при ПОЛОВИН риск: PORTFOLIO_SIZE × RISK_PER_TRADE_PCT × 0.5 ($500 при $1000)
QM_MAX_POSITION_PCT = float(os.getenv("QM_MAX_POSITION_PCT", 30))   # негово: не повече от 30% от сметката в един инструмент за през нощта
# Изход и книга "qm_breakout" (trade_sim.simulate_qm — същата функция в реплея и в Track Record-а)
TRACK_QM = os.getenv("TRACK_QM", "1") == "1"
QM_ENTRY_WINDOW_SESSIONS = 1                                     # кандидатът е валиден за ЕДНА сесия (деня на брифа)
QM_CHASE_ADR = 1.0                                               # не се гони гап над нивото с повече от 1× ADR
QM_ADR_STOP = 1.0                                                # стоп (вход − low на деня) ≤ 1× ADR, иначе записът е "skipped_adr"
QM_PARTIAL_DAYS = int(os.getenv("QM_PARTIAL_DAYS", 4))           # негово: 1/3–1/2 след 3–5 дни → затварянето на 4-тата сесия след входния ден
QM_PARTIAL_FRACTION = float(os.getenv("QM_PARTIAL_FRACTION", 0.4))   # среда на 1/3–1/2
QM_TRAIL_ADR_SWITCH = float(os.getenv("QM_TRAIL_ADR_SWITCH", 5.0))   # остатъкът по SMA10 при ADR ≥ 5%, иначе по SMA20 (първо затваряне под)
QM_MAX_HOLD_SESSIONS = int(os.getenv("QM_MAX_HOLD_SESSIONS", 180))
QM_MIN_CLOSED_FOR_WINRATE = int(os.getenv("QM_MIN_CLOSED_FOR_WINRATE", 20))
# EP наблюдение (src/qm_ep.py): само информация, без Track Record
ENABLE_QM_EP = os.getenv("ENABLE_QM_EP", "1") == "1"
QM_EP_GAP_PCT = float(os.getenv("QM_EP_GAP_PCT", 10.0))          # негово: гап нагоре ≥ 10% (тук — after-hours цена спрямо затварянето)
QM_EP_NEGLECT_RET63_PCT = float(os.getenv("QM_EP_NEGLECT_RET63_PCT", 20.0))   # "пренебрегване": ръст за предходните ~3 месеца ≤ 20%
QM_EP_STOP_ADR = float(os.getenv("QM_EP_STOP_ADR", 1.0))         # информация: максимален стоп 1× ADR (негово: 1×, най-много 1.5×)
QM_EP_MAX_ROWS = int(os.getenv("QM_EP_MAX_ROWS", 10))
QM_EP_MIN_AH_BARS = 3                                            # поне толкова 5-минутни after-hours бара (иначе няма реална търговия)
QM_EP_BATCH = 100

# ── Режим → Action (пакет 1, т.6 — 2026-10-03) ────────────────────────────
# Cash → никакъв нов Action (капиталът е позиция); Defensive → Action само при Entry Timing
# "good" (0…+ENTRY_TIMING_EXTENDED_PCT% над pivot, с обем); Offensive → без ограничение.
# Блокираните отиват във Watchlist с причина "regime_block" (БЕЗ 10-дневното изтичане на
# "regime_gate" — те се преоценяват сами всеки ден). Преди: Cash даваше Action с ×0.5 риск.
# Реплей 02.01.2024 → 02.10.2026 (v2 сигнали, обем ≥1.4×, хоризонт 20 дни; режим = реалният
# от 12.06.2026, преди това прокси "SPY над 50 и 200DMA"): Offensive 641 сигнала → win 50%,
# среден R +0.08 ± 0.04; Defensive 172 → win 46%, R −0.11 ± 0.07 (разлика 2.4σ). Вътре в
# Defensive "good ≤2%" (109 сигнала, R −0.12) НЕ се различава от "2–5%" (63, R −0.08;
# разлика ±0.14) — филтърът реже ~37% от сигналите, но данните не показват, че ги подобрява.
# Cash в историята няма (прокси без Cash). Двата превключвателя позволяват връщане без код.
REGIME_CASH_BLOCKS_ACTION = os.getenv("REGIME_CASH_BLOCKS_ACTION", "1") == "1"
REGIME_DEFENSIVE_REQUIRES_GOOD_TIMING = os.getenv("REGIME_DEFENSIVE_REQUIRES_GOOD_TIMING", "1") == "1"

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

# Минимум ВИДИМИ индикатори (от 8 БРОЕНИ), за да е допустим Offensive. Скрит индикатор
# (невалидни/застояли данни) не участва в броенето, затова без този праг 5 зелени
# от 5 видими даваха Offensive с пълен sizing (08.09: 4 от 9 скрити). Под прага
# режимът е Defensive с причина "недостатъчно данни".
# 2026-10-03 (пакет 2 т.2): Fed Net Liquidity стана САМО информативен (не се брои), затова
# бройките са 8 вместо 9 и прагът е 6 от 8 (беше 7 от 9 — същата пропорция ~75%).
THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE = int(os.getenv("THERMOMETER_MIN_VISIBLE_FOR_OFFENSIVE", 6))

# 2026-10-03 (пакет 2 т.3): Put/Call на SPY — калибриран спрямо СОБСТВЕНАТА история (percentile, като IEI/HYG), не
# спрямо фиксирани 1.1/0.7. Проблемът: P/C на най-близкия SPY експирейшън има медиана 1.12 (хеджиране) — старият праг
# "над 1.1 → зелено" правеше индикатора зелен в 42 от 78 дни (54%), червен само 2 пъти. Сега: висок percentile
# (страх, contrarian) → зелено, нисък (самодоволство) → червено; крайните 10% от двете страни, както IEI/HYG (спайк 90.,
# ниво 10.) — "малко, но значимо", за да не раздува червените в броенето. Реплей върху 78-те снимки (без поглед напред,
# първите 30 дни скрити): 90/10 → зелено 13 / жълто 31 / червено 4 / скрито 30; в стационарно състояние 10/80/10%.
# Алтернативата 80/20 дава 20% червени и 5 дни с различен режим (срещу 3). История: най-много PUTCALL_LOOKBACK дни, поне
# PUTCALL_MIN_HISTORY, иначе индикаторът се скрива; пази се в data/put_call_history.json (при липса — от брифовете).
PUTCALL_PERCENTILE_GREEN = float(os.getenv("PUTCALL_PERCENTILE_GREEN", 90))
PUTCALL_PERCENTILE_RED = float(os.getenv("PUTCALL_PERCENTILE_RED", 10))
PUTCALL_MIN_HISTORY = int(os.getenv("PUTCALL_MIN_HISTORY", 30))
PUTCALL_LOOKBACK = int(os.getenv("PUTCALL_LOOKBACK", 252))

# ── API ключове (от GitHub Secrets / .env) ───────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
# NEWS_API_KEY е махнат (2026-10-03): NewsAPI даде 0 заглавия за 78 дни; новините са news_aggregator (RSS/nitter + Claude филтър)
# TRADIER_API_KEY / TRADIER_BASE — виж v2 секцията по-долу (заедно с коментара им)

# ── Имейл доставка ────────────────────────────────────────────────────────
EMAIL_METHOD = os.getenv("EMAIL_METHOD", "smtp")    # "smtp" | "sendgrid"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://venc74.github.io/market-brief/")

# ── Claude модел ──────────────────────────────────────────────────────────
# CLAUDE_MODEL е РАБОТНАТА стойност — model_selector.resolve_model() я
# презаписва в началото на всеки run, а _call_claude я чете при всяко
# извикване, така че всички AI стъпки наследяват избора автоматично.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
# Изрично зададен env → печели, discovery не се пуска (escape hatch при
# проблем с нов модел: една променлива в workflow-а, без code промяна).
CLAUDE_MODEL_PINNED = os.getenv("CLAUDE_MODEL") is not None
# Известният работещ модел. Използва се при всеки провал — недостъпен Models
# API, празен списък, паднал probe.
CLAUDE_MODEL_FALLBACK = os.getenv("CLAUDE_MODEL_FALLBACK", "claude-sonnet-4-6")
# FIX 2026-09-23 (политика): ИЗКЛЮЧЕН по подразбиране. Първият автоматичен
# избор (claude-sonnet-5, 23.09) излезе повреден и по-скъп — новият модел
# включва adaptive thinking по подразбиране и ползва нов tokenizer (~30% повече
# токени за същия текст), и двете изяждат лимити, калибрирани за 4.6. Смяна на
# модел занапред — само с изрична команда (CLAUDE_MODEL в workflow-а). Probe-ът
# и банерът остават и при ръчна смяна.
MODEL_AUTO_SELECT = os.getenv("MODEL_AUTO_SELECT", "0") == "1"
# Колко ПОСЛЕДОВАТЕЛНИ run-а стои банерът след смяна на модела.
MODEL_BANNER_RUNS = int(os.getenv("MODEL_BANNER_RUNS", 5))
MODEL_PROBE_MAX_TOKENS = int(os.getenv("MODEL_PROBE_MAX_TOKENS", 16))

# FIX 2026-09-23: изричен лимит за macro_and_sector_brief. Дотук извикването
# не подаваше max_tokens и падаше на default-а 4000 на _call_claude.
# Измерено срещу 70 дни на 4.6: изходът е медиана 4 770 знака, p95 5 797,
# макс. 6 074 — най-големият единичен изход в pipeline-а. Реални token числа
# няма откъде да се видят (Actions логът иска автентикация) — от този fix
# нататък всяко извикване записва usage в брифа (ai_brief.AI_USAGE).
# max_tokens е ТАВАН, не такса: плаща се само реално генерираното, затова
# запасът не струва нищо, а отрязването струва секция.
MACRO_MAX_TOKENS = int(os.getenv("MACRO_MAX_TOKENS", 8000))

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
QM_EP_LOG_FILE = DATA_DIR / "ep_ah_log.json"       # пакет QM: after-hours гапът срещу реалния гап на отварянето — за решение след 4–6 седмици дали си струва второ пускане
PUTCALL_HISTORY_FILE = DATA_DIR / "put_call_history.json"

# ── Секторни ETF-и за ротационен анализ (Слой 2) ─────────────────────────
SECTOR_ETFS = {
    "XLK": "Технологии", "XLE": "Енергетика", "XLF": "Финанси",
    "XLV": "Здравеопазване", "XLI": "Индустрия", "XLB": "Материали",
    "XLY": "Потребителски (циклични)", "XLP": "Потребителски (защитни)",
    "XLU": "Комунални услуги", "XLRE": "Недвижими имоти", "XLC": "Комуникации",
    "ITA": "Отбрана", "GDX": "Златодобив", "URA": "Уран/ядрена", "TAN": "Соларна",
    "SMH": "Полупроводници", "XBI": "Биотех", "KOL_PROXY_BTU": "Въглища (proxy)",
}


# 2026-10-03 (пакет 2 т.1): мост секторен ETF → Yahoo "sector"/"industry" на кандидатите. leading_sectors()
# връща български имена ("Технологии"), а картите носят английските Yahoo полета ("Technology") — старото
# сравнение на подниз беше False за всичките 645 карти от 78-те брифа (macro_tailwind никога не се сетваше).
# Всяка ETF е сектор (11 SPDR) или тясна индустрия (ITA, GDX, URA, TAN, SMH, XBI); съвпадението е точно, без
# регистър. Само сортиране и маркер SECT✓ — НЕ филтър.
SECTOR_ETF_YAHOO = {
    "XLK": {"sector": ["Technology"]}, "XLE": {"sector": ["Energy"]}, "XLF": {"sector": ["Financial Services"]},
    "XLV": {"sector": ["Healthcare"]}, "XLI": {"sector": ["Industrials"]}, "XLB": {"sector": ["Basic Materials"]},
    "XLY": {"sector": ["Consumer Cyclical"]}, "XLP": {"sector": ["Consumer Defensive"]},
    "XLU": {"sector": ["Utilities"]}, "XLRE": {"sector": ["Real Estate"]}, "XLC": {"sector": ["Communication Services"]},
    "ITA": {"industry": ["Aerospace & Defense"]}, "GDX": {"industry": ["Gold"]}, "URA": {"industry": ["Uranium"]},
    "TAN": {"industry": ["Solar"]}, "XBI": {"industry": ["Biotechnology"]},
    "SMH": {"industry": ["Semiconductors", "Semiconductor Equipment & Materials"]},
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
# FIX 2026-09-29: "sector_etf" — секторът за карето "Контекст" (src/
# thesis_context.py); трябва да е ключ от SECTOR_ETFS, иначе "—".
# "sector_etf_label" — изричен надпис, когато ETF-ът е прокси.
THESIS_BASKETS = [
    {
        "name": "Въглища и LNG",
        # FIX 2026-09-29: CEIX → CNR (CONSOL + Arch = Core Natural Resources от
        # 15.01.2025); TELL махнат (купена от Woodside, сделката приключи 08.10.2024).
        # И двата мълчаха месеци без ценови данни.
        "tickers": ["BTU", "HCC", "AMR", "CNR", "LNG"],
        # една акция (BTU) не измерва сектор → енергетиката като прокси
        "sector_etf": "XLE", "sector_etf_label": "прокси: енергетика",
        "default_status": "watch",
        "trigger": "oil_shock",
        "chain": ("Петролен шок или напрежение в Близкия изток → скок в цената на "
                  "енергията → въглищата и LNG поемат търсенето, което петролът не "
                  "може → маржовете на тези производители се разширяват рязко."),
    },
    {
        "name": "Ядрена енергия",
        "tickers": ["VST", "CEG", "OKLO", "CCJ", "DNN", "NNE"],
        "sector_etf": "URA",
        "default_status": "structural",
        "trigger": None,
        "chain": ("AI data center-ите гладуват за стабилна базова мощност 24/7 → "
                  "ядрената е единственият въглеродно-неутрален източник, който я "
                  "дава → дългосрочно търсене на уран и реакторни оператори."),
    },
    {
        "name": "Отбрана и дронове",
        "tickers": ["LMT", "RTX", "NOC", "SWMR"],
        "sector_etf": "ITA",
        "default_status": "watch",
        "trigger": "geopolitical_stress",
        "chain": ("Геополитическа ескалация → държавите вдигат отбранителни бюджети → "
                  "поръчки с многогодишен backlog за големите изпълнители → предвидим "
                  "приходен поток независим от икономическия цикъл."),
    },
    {
        "name": "Крипто регулация (CLARITY Act)",
        "tickers": ["CRCL", "COIN", "HOOD", "BLSH"],
        "sector_etf": None,  # няма крипто ETF в SECTOR_ETFS → "—"
        "default_status": "watch",
        "trigger": None,
        "chain": ("Ясна законодателна рамка (CLARITY Act) → институциите получават "
                  "регулаторна сигурност → приток на капитал към регулирани крипто "
                  "борси и custody → борсите и брокерите печелят на обем."),
    },
    {
        "name": "Полупроводници и AI инфраструктура",
        "tickers": ["AVGO", "AMAT", "MCHP"],
        "sector_etf": "SMH",
        "default_status": "structural",
        "trigger": None,
        "chain": ("AI build-out → търсене не само на GPU, а на цялата верига: mature-"
                  "node чипове, оборудване за производство, liquid cooling, мрежи и "
                  "захранване → вторичните доставчици печелят с по-малко конкуренция."),
    },
    {
        "name": "Финанси при стръмна крива",
        "tickers": ["JPM", "BAC"],
        "sector_etf": "XLF",
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
# FIX 2026-09-29: каре "Контекст" към маркираните тези (src/thesis_context.py)
# — само данни от кода, без AI текст. Проверката за липсващи ценови данни
# важи за ВСИЧКИ тези (CEIX/TELL мълчаха месеци).
ENABLE_THESIS_CONTEXT = os.getenv("ENABLE_THESIS_CONTEXT", "1") == "1"


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
# верифициран списък от 15 мениджъра. DATAROMA_MANAGERS (dataroma.com URL
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
# FIX 2026-09-15: "allinurl:" операторът беше спрял да връща резултати в Google
# News RSS — HTTP 200, валиден RSS, коректно ехо на заявката, НУЛА <item>-а.
# Проверено directamente: allinurl:reuters.com → 0 items (и с when:24h, и без,
# и при when:7d), докато site:reuters.com → 100 items, същия ден, същия формат.
# Тиха загуба на 2 от 4 източника; потвърдено последствие — на 15.09 Reuters
# заглавието "US Senate to vote on advancing landmark crypto bill" (реалният
# CLARITY Act cloture vote) изобщо не стигна до Claude филтъра.
NEWS_RSS_FEEDS = {
    "Reuters Business": "https://news.google.com/rss/search?q=when:24h+site:reuters.com&hl=en-US&gl=US&ceid=US:en",
    "CNBC":             "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "Financial Times":  "https://www.ft.com/rss/home",
    "AP Business":      "https://news.google.com/rss/search?q=when:24h+site:apnews.com&hl=en-US&gl=US&ceid=US:en",
}
# FIX 2026-09-16: заглавия под ранг 15 изобщо не влизаха в събраното. Потвърдено
# на 16.09 — Reuters "Crypto bill's defeat shows limits of industry's political
# machine" (провалилият се CLARITY cloture vote от 15.09) стои на ранг 17, в
# 24-часовия прозорец и напълно достижим, но под стария limit=15.
#
# Вдигането само на limit НЕ е достатъчно: старият агрегатен таван raw[:60]
# реже след конкатенация по източници, затова limit=30 даваше
# {Reuters: 30, CNBC: 30, FT: 0, AP: 0} — точно обратното на fix-а от 15.09.
# Затова заглавията се РЕДУВАТ между източниците (виж news_aggregator.
# _interleave), а таванът е вдигнат. Измерено срещу реалните емисии на 16.09:
#   limit=15, таван 60, конкатенация  → 55 загл., 4 източника, целевото НЕ минава
#   limit=30, таван 60, конкатенация  → 60 загл., 2 източника (FT/AP нула)
#   limit=50, таван 60, редуване      → 60 загл., 4 източника, целевото НЕ минава
#   limit=50, таван 100, редуване     → 100 загл., 4 източника, целевото МИНАВА ✓
# Цена: ~3100 → ~5600 входни токена за едно извикване на дневния news филтър.
NEWS_PER_SOURCE_LIMIT = int(os.getenv("NEWS_PER_SOURCE_LIMIT", 50))
NEWS_MAX_TO_FILTER = int(os.getenv("NEWS_MAX_TO_FILTER", 100))
# Свереност на геополитическите тези срещу днешните новини (ai_brief.
# thesis_reality_check) — едно допълнително извикване на ден, само анотация,
# не пипа thesis status-а. Изходът е ≤6 кратки обекта, 1000 стигат с запас.
# FIX 2026-09-30: 1000 → 2000. Структурните полета за G1–G3 (basis, subject_ticker,
# affected_tickers, effect, chain_quote, event_type) са ~190 знака на маркирана
# теза; реалният изход е ~2.8–3 знака/токен (24/29/30.09), песимистично 1.6 →
# ~120 токена. Максимумът досега е 791/1000 (25.09, 0 маркирани); с полета за
# всичките 6 тези ≈ 1 500 → 1000 би отрязал и скрил ЦЯЛАТА проверка.
THESIS_CHECK_MAX_TOKENS = int(os.getenv("THESIS_CHECK_MAX_TOKENS", 2000))
# Минимална дължина на бележката при news_status="evolving" (виж
# ai_brief.thesis_reality_check). "evolving" изисква да се назоват И ДВАТА пътя —
# спрян оригинал И конкретна алтернатива — което не се побира в едно късо
# твърдение. Кодът не може да провери семантиката, но може да отхвърли бележка,
# която очевидно не носи двете. Праг, не гаранция.
THESIS_EVOLVING_MIN_NOTE_CHARS = int(os.getenv("THESIS_EVOLVING_MIN_NOTE_CHARS", 80))

# ── 🔎 Наблюдавани тикъри (watch_monitor.py) ──────────────────────────────
# Ръчно куриран, per-ticker дневен монитор. Списъкът е в data/watch_list.json
# и се редактира НА РЪКА — сайтът е статичен, няма backend за интерактивен бутон.
ENABLE_WATCH_MONITOR = os.getenv("ENABLE_WATCH_MONITOR", "1") == "1"
WATCH_NEWS_WINDOW_HOURS = int(os.getenv("WATCH_NEWS_WINDOW_HOURS", 24))
WATCH_MAX_NEWS_PER_TICKER = int(os.getenv("WATCH_MAX_NEWS_PER_TICKER", 6))
# Form 4 подаването изостава от самата сделка с дни — 30д прозорец улавя и
# закъснели filings, AI-то вижда датата на транзакцията и преценява сам.
WATCH_INSIDER_LOOKBACK_DAYS = int(os.getenv("WATCH_INSIDER_LOOKBACK_DAYS", 30))
WATCH_MAX_TOKENS = int(os.getenv("WATCH_MAX_TOKENS", 2000))
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
# FIX 2026-09-12 (findings log 04-11.09): yfinance-ното openInterest поле
# понякога връща непълни/stale данни за multi-day прозорец (потвърдено:
# 08-11.09, 4 последователни дни, за едни и същи mega-cap тикъри — same
# volume, reconstructed OI пада от реалистичните ~70K-630K до 51-771,
# стотици пъти по-малко). Съществуващият total_oi>=50 (контракти) guard
# хваща само буквална нула/near-нула — множество "счупени" стойности
# кацаха точно над него (51, 52, 60...). Горен sanity ceiling на САМОТО
# съотношение хваща класа проблем директно: реалният здрав максимум тази
# седмица беше 21.6× (KDP, 04.09), реалният "счупен" минимум беше 176.1×
# (WMT, 11.09) — огромна пропаст, 50× седи comfortably по средата. Same
# принцип като IV sanity floor прецедента (src/enrich.py) — горна граница
# на правдоподобност, не само долна.
UNUSUAL_OPTIONS_MAX_OI_RATIO = float(os.getenv("UNUSUAL_OPTIONS_MAX_OI_RATIO", 50.0))
# FIX 2026-09-28: под толкова показани тикъра със съотношение обем/OI секцията
# казва изрично, че подредбата е по ликвидност (от 21.09: 1–3/10 всеки ден)
UNUSUAL_OPTIONS_MIN_RATIOS = int(os.getenv("UNUSUAL_OPTIONS_MIN_RATIOS", 5))

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
# FIX 2026-09-29: OI за съотношението идва от следобедна снимка (отделен
# GitHub Actions job, .github/workflows/oi_snapshot.yml → src/oi_snapshot.py),
# не от сутрешния fetch. Проба 29.09: в 05:40 UTC OI е 0 за седмичните падежи
# и непълен за месечните (APH 38 734 в 05:35 срещу 248 232 в 13:09 UTC за
# същите падежи; HBAN 4 903 срещу 72 042). Сутрешният бриф сравнява вчерашния
# обем с OI в началото на вчерашната сесия = това, което Yahoo има следобед.
UNUSUAL_OPTIONS_OI_SNAPSHOT_FILE = DATA_DIR / "unusual_options_oi_snapshot.json"
# Колко тикъра снима следобедът: утрешният списък се ранжира наново, затова
# резерв над SCAN_LIMIT. Измерено по 61 дни от git историята на ранжирането:
# с топ 80 утрешните топ 60 липсват само 2 пъти по 1 тикър (без еднократната
# смяна на универса 13→14.07); с топ 60 — 37 от 60 дни.
# Пакет 4б т.б: списъкът "Unusual Options" отпадна — снимката вече е за НАШИТЕ тикъри (кандидатите от последните брифове и позициите, виж
# oi_snapshot.snapshot_tickers); това е допълнителен брой най-ликвидни тикъри (0 = само кандидати и позиции).
UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS = int(os.getenv("UNUSUAL_OPTIONS_OI_SNAPSHOT_TICKERS", 0))
# Колко от последните брифове дават кандидати за снимката (Watchlist стои няколко дни, утрешните кандидати са почти същите като днешните)
UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS = int(os.getenv("UNUSUAL_OPTIONS_SNAPSHOT_BRIEF_DAYS", 5))
# Маркер UOV✓ върху кандидат/позиция: съотношението обем/OI по прозореца (виж UNUSUAL_OPTIONS_HORIZON_DAYS) поне толкова. 2.0 е границата на старото
# "силно ново позициониране" (_oi_label); НЕ е калибрирана на новия прозорец — съотношенията на ВСИЧКИ сканирани тикъри се пишат в brief["uov_diag"],
# за да се калибрира по реални дни. Таван на тикърите на едно извикване (всеки тикър = до ~14 заявки за вериги).
UNUSUAL_OPTIONS_MARKER_MIN_RATIO = float(os.getenv("UNUSUAL_OPTIONS_MARKER_MIN_RATIO", 2.0))
UNUSUAL_OPTIONS_MARKER_MAX_TICKERS = int(os.getenv("UNUSUAL_OPTIONS_MARKER_MAX_TICKERS", 40))
# ОСТАРЯЛО от пакет 4б т.а (06.10.2026): снимката вече пази OI по ВРЕМЕВИ прозорец (виж UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS), не "първите N
# падежа". Константата се чете само от стария формат на снимките.
UNUSUAL_OPTIONS_OI_SNAPSHOT_EXPIRATIONS = int(os.getenv("UNUSUAL_OPTIONS_OI_SNAPSHOT_EXPIRATIONS", 4))
# Пакет 4б т.а: съотношението обем/OI е сравнимо между дните само ако знаменателят е от ЕДИН И СЪЩ времеви прозорец, не от "най-близките 2 падежа".
# Измерено на жива верига (05.10.2026, TSLA/NVDA/AAPL): при плъзгане на деня на брифа от пон до пет "най-близките 2 падежа" се клатят ×15–×26
# (петъчният седмичен падеж държи 60–70% от OI и влиза/излиза според деня), прозорец от 21 дни — ×1.2–×1.4. Падеж, изтекъл или изтичащ в деня
# на брифа, не участва; обемът и OI са по едни и същи падежи (падеж без OI в снимката отпада и от двете страни).
UNUSUAL_OPTIONS_HORIZON_DAYS = int(os.getenv("UNUSUAL_OPTIONS_HORIZON_DAYS", 21))
# Снимката пази OI за падежите в (сесия, сесия + 28 дни]: брифът е най-много 4 дни след сесията (уикенд + празник), а прозорецът му стига до +21.
UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS = int(os.getenv("UNUSUAL_OPTIONS_OI_SNAPSHOT_HORIZON_DAYS", 28))
# Таван на падежите на тикър (дълги вериги със седмични падежи Пн/Ср/Пт): повече вериги = повече заявки, а по-далечните тежат малко
UNUSUAL_OPTIONS_MAX_EXPIRIES = int(os.getenv("UNUSUAL_OPTIONS_MAX_EXPIRIES", 14))
# Колко снимки се пазят (по дата на сесията)
UNUSUAL_OPTIONS_OI_SNAPSHOT_KEEP = int(os.getenv("UNUSUAL_OPTIONS_OI_SNAPSHOT_KEEP", 7))
# FIX 2026-10-01 (отговор на прегледа на партида 1, т.4): oi_snapshot.yml има
# и schedule: (15:00 UTC), и workflow_dispatch от cron-job.org — двата може
# да стрелят за същия ден (GitHub-native scheduler закъснява с часове,
# наблюдавано: 19:55 UTC и 18:22 UTC за 30.09/29.09). Без guard втория run
# презаписва снимка, която вече е добра, без полза, само похабен fetch.
# FIX 2026-10-02 (т.5): прозорецът на валиден OI следва часа в НЮ ЙОРК, не
# фиксиран UTC — търговската сесия е 09:30–16:00 ET = 13:30–20:00 UTC през лятото
# (EDT) и 14:30–21:00 UTC през зимата (EST; САЩ минават на зимно време на
# 01.11.2026). Фиксирано "20:00 UTC" би пропускало валидни пускания 20:00–21:00
# UTC след 01.11. След тази граница run без добра снимка се пропуска вместо да
# пази данни извън измерения прозорец. Само краят се налага; началото не (13:09 UTC
# пробата от 29.09 вече даваше пълен OI).
UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_NY_HOUR = int(
    os.getenv("UNUSUAL_OPTIONS_OI_SNAPSHOT_CUTOFF_NY_HOUR", 16))
# Колко % от заявените тикъри трябва да са успешни, за да е снимката "пълна"
# (и поне половината от тях с OI ≥ 50) — непълна снимка не блокира повторен опит
UNUSUAL_OPTIONS_OI_SNAPSHOT_MIN_COMPLETE_PCT = float(
    os.getenv("UNUSUAL_OPTIONS_OI_SNAPSHOT_MIN_COMPLETE_PCT", 90))

# ── SEC EDGAR 13F (Поправка 3): primary за Superinvestor Positions ─────────
# EDGAR изисква descriptive User-Agent с реален контакт — стойността се
# подава само през env var (GitHub Secret), никога не се комитва в кода.
EDGAR_UA = os.getenv("EDGAR_UA", "market-brief-bot (contact via GitHub repo)")
# CIK номера — верифицирани directamente през data.sec.gov/submissions
# (не по име само — вижте FIX бележките, две грешки хванати точно така).
# 15 мениджъра общо. Ключ = CIK (10 цифри, нулево-допълнен), стойност = име.
#
# 2026-10-03: Майкъл Бъри / Scion Asset Management (CIK 0001649339) е махнат от списъка —
# фондът е закрит (последен filing 2025-11-03), т.е. нямаше какво да се чете. Механизмът за
# мениджъри, спрели да подават 13F (DATAROMA_STALE_FILER_DAYS → "stopped" → отделен ред във
# "Major Position Exits"), е непроменен и важи за всеки бъдещ спрял мениджър.
#
# FIX 2026-08-17: старият Klarman CIK (0001061219) сочеше към ENTERPRISE
# PRODUCTS PARTNERS L.P. — напълно различна компания, никога не е бил Baupost.
# Верен CIK: 0001061768 (BAUPOST GROUP LLC/MA).
#
# FIX 2026-08-17: Разширяване от 5 на 16 мениджъра (15 след махането на Scion на 2026-10-03). Първите по име съвпадения
# за Tepper/Appaloosa, Marks/Oaktree, Armitage/Egerton и Pabrai бяха ОТДАВНА
# НЕАКТИВНИ entity-та (фирмите преминават към нови SEC filing CIK-ове с
# годините — последен filing 2016/2011/2013/2012 съответно) — наложи се
# допълнително търсене за текущите активни filers. Pabrai's официална SEC
# filing entity се оказа "Dalal Street, LLC", не "Pabrai"/"Pabrai Investments".
DATAROMA_CIK = {
    "0001067983": "Уорън Бъфет · Berkshire Hathaway",
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
# FIX 2026-08-20: дизайнерският lookback е 156 седмици (~3г, cot.py:
# _LOOKBACK_WEEKS), но по-скоро добавени контракти (напр. XRP на CME,
# launched ~юли 2025) имат много по-кратка налична история — percentile
# спрямо 53 седмици е статистически по-малко сигурен от percentile спрямо
# пълните 156. Праг под който AI-то трябва explicit да flag-не по-ниската
# увереност в generирания текст (same честен дух като GLB ath_label
# разграничението — не тихо наблюдение в кода, а видимо в reasoning-а).
# 104 седмици (~2г) е разумен cutoff: достатъчно под 156 да хване genuinely
# нови контракти, достатъчно над ~52 да не флагва обикновени, добре
# established пазари с временни data gaps.
COT_SHORT_HISTORY_WEEKS = int(os.getenv("COT_SHORT_HISTORY_WEEKS", 104))
# FIX 2026-10-03 (пакет 2 т.7): давност на COT. Отчетът е към вторник и излиза в петък следобед, затова нормалната
# възраст на най-новия отчет по време на сутрешния бриф е 6–10 дни (реално: 64 от 65 брифа с COT редове, 06.07–02.10.2026,
# бяха 6–10 дни). Седмица с празничен петък мести излизането в понеделник и дава 13 дни — 06.07.2026 (3 юли беше почивен):
# най-новият отчет е 23.06, 13 дни. Праг 12 би дал фалшива тревога точно тогава, затова "стар" е СТРОГО повече от 13 дни
# (= пропуснат цял седмичен отчет, виден от вторника след него). Над прага секцията COT показва банер.
COT_STALE_DAYS = int(os.getenv("COT_STALE_DAYS", 13))
COT_BATCH_SIZE = int(os.getenv("COT_BATCH_SIZE", 5))
# FIX 2026-09-28: 3000 → 4000. На 28.09 batch-овете стигнаха до 2162/3000;
# Release 2 добавя effect на тикър + assumed_move + no_direct_link (~+300).
COT_BATCH_MAX_TOKENS = int(os.getenv("COT_BATCH_MAX_TOKENS", 4000))
# FIX 2026-08-02: горна граница на running seen_tickers речника (soft cross-batch
# consistency, ai_brief.py: cot_theses) — FIFO, за да не расте prior_context
# неограничено на дни с много batch-ове/тикъри.
COT_SEEN_TICKERS_CAP = int(os.getenv("COT_SEEN_TICKERS_CAP", 20))

# ══════════════════════════════════════════════════════════════════════════
# Пакет 3 (2026-10-05) — COT тези: таблици, които държи КОДЪТ (не моделът)
# ══════════════════════════════════════════════════════════════════════════
# Вид на пазара — определя кой знак важи за даден механизъм (виж COT_MECHANISM_SIGN) и как се чете "цената":
#   equity_index (индекс), volatility (VIX), fx_foreign (чужда валута срещу USD: цена↑ = валутата поскъпва),
#   fx_usd (US Dollar Index: цена↑ = доларът поскъпва), rate (облигационен фючърс: цена↑ = доходността ПАДА),
#   crypto, commodity. Записите покриват всичките 40 пазара от cot.MAJOR_MARKETS (тест: test_cot_tables.py).
COT_MARKET_KINDS = {
    "E-mini S&P 500": "equity_index", "Nasdaq-100": "equity_index", "E-mini Russell 2000": "equity_index",
    "E-mini Dow (DJIA)": "equity_index", "VIX Futures": "volatility", "US Dollar Index": "fx_usd",
    "Euro FX": "fx_foreign", "Japanese Yen": "fx_foreign", "British Pound": "fx_foreign", "Swiss Franc": "fx_foreign",
    "Canadian Dollar": "fx_foreign", "Australian Dollar": "fx_foreign", "Mexican Peso": "fx_foreign",
    "2-Year Treasury Note": "rate", "5-Year Treasury Note": "rate", "10-Year Treasury Note": "rate",
    "Ultra Treasury Bond": "rate", "30-Year Treasury Bond": "rate",
    "Bitcoin Futures (CME)": "crypto", "XRP": "crypto",
    "Gold": "commodity", "Silver": "commodity", "Copper": "commodity", "Platinum": "commodity", "Palladium": "commodity",
    "WTI Crude Oil": "commodity", "Natural Gas": "commodity", "RBOB Gasoline": "commodity", "Heating Oil": "commodity",
    "Corn": "commodity", "Soybeans": "commodity", "Soybean Oil": "commodity", "Soybean Meal": "commodity",
    "Wheat": "commodity", "Sugar No. 11": "commodity", "Coffee C": "commodity", "Cocoa": "commodity", "Cotton": "commodity",
    "Lean Hogs": "commodity", "Live Cattle": "commodity",
}

# Затворен списък от типове механизъм (пакет 3 т.г): моделът връща за всеки cross тикър 1–2 механизма {type, quote};
# ЕФЕКТЪТ (печели/губи) се изчислява от кода по тази таблица, не от модела. "sign" = ефектът върху компанията, когато ЦЕНАТА
# на инструмента РАСТЕ (при падане е обратното): +1 печели, −1 губи; по вид на пазара (виж COT_MARKET_KINDS). Тип, който не е
# валиден за вида на пазара, се отхвърля като невалидна схема. "direct": пряк механизъм ли е — типове 7, 8, 10 (index_beta,
# risk_off_hedge, consumer_wallet) и "other" НИКОГА не са пряк механизъм: отворена позиция не влиза в cross теза с тях
# (значката "отворена позиция" се слага само при пряк механизъм); "other" не показва посока. Два механизма с противоположен
# знак → "mixed" → тикърът се изключва. "text" е дефиницията, която влиза в промпта (и е част от версията му).
COT_MECHANISM_SIGN = {
    "input_cost":              {"label": "разход за суровина", "direct": True,  "sign": {"commodity": -1},
                                "text": "компанията КУПУВА инструмента като суровина/разход — по-висока цена = по-високи разходи"},
    "output_price":            {"label": "цена на продукта", "direct": True,  "sign": {"commodity": +1},
                                "text": "компанията ПРОДАВА инструмента или продукт, чиято цена го следва — по-висока цена = по-високи приходи"},
    "fx_revenue_translation":  {"label": "валутен превод на приходи", "direct": True,  "sign": {"fx_foreign": +1, "fx_usd": -1},
                                "text": "значителна част от приходите са в чужда валута и се превеждат в USD — по-силна чужда валута = повече USD приходи"},
    "fx_cost_local":           {"label": "разходи в чужда валута", "direct": True,  "sign": {"fx_foreign": -1, "fx_usd": +1},
                                "text": "значителна част от разходите са в чужда валута — по-силна чужда валута = по-високи разходи в USD"},
    "rate_asset_yield":        {"label": "доходност на активите", "direct": True,  "sign": {"rate": -1},
                                "text": "компанията печели от по-високи доходности (лихвен марж, реинвестиране) — цена на облигацията НАГОРЕ = доходност НАДОЛУ = по-малко печалба"},
    "rate_duration_valuation": {"label": "оценка при дълга дюрация", "direct": True,  "sign": {"rate": +1},
                                "text": "дългосрочни парични потоци/оценка (дълга дюрация) — доходност НАДОЛУ (цена на облигацията НАГОРЕ) = по-висока оценка"},
    "index_beta":              {"label": "бета към пазара", "direct": False, "sign": {"equity_index": +1, "volatility": -1, "crypto": +1},
                                "text": "тикърът се движи с широкия пазар/риск апетита (бета), не заради конкретен бизнес механизъм"},
    "risk_off_hedge":          {"label": "защитен актив", "direct": False, "sign": {"equity_index": -1, "volatility": +1, "crypto": -1},
                                "text": "тикърът расте, когато пазарът бяга от риск (защитен актив)"},
    "substitute":              {"label": "заместител", "direct": True,  "sign": {"commodity": +1},
                                "text": "компанията продава заместител на инструмента — по-висока цена на инструмента = повече търсене на заместителя"},
    "consumer_wallet":         {"label": "потребителски бюджет", "direct": False, "sign": {"commodity": -1},
                                "text": "клиентите на компанията харчат по-малко, когато цената на инструмента расте (потребителски бюджет)"},
    "other":                   {"label": "друг механизъм", "direct": False, "sign": {},
                                "text": "друг механизъм извън списъка — без изчислена посока"},
}
# Вид на пазара — как се чете "цената" (влиза в промпта към модела)
COT_KIND_TEXT = {
    "equity_index": "борсов индекс (цена↑ = пазарът расте)", "volatility": "волатилност VIX (цена↑ = страх на пазара)",
    "fx_foreign": "чужда валута срещу USD (цена↑ = валутата поскъпва спрямо долара)", "fx_usd": "US Dollar Index (цена↑ = доларът поскъпва)",
    "rate": "облигационен фючърс (цена↑ = доходността ПАДА)", "crypto": "криптовалута", "commodity": "стока",
}
# Cross-sector (пакет 3 т.г): колко тикъра и механизма, максимална дължина на описанието (quote)
# Кеш на COT тезите (пакет 3 т.а): data/cot_theses_cache.json. Ключ: (пазар, as_of, посока на екстремума, версия на промпта/схемата,
# модел). Регенерация само при нов as_of, нова посока, нов екстремум (нов ключ), смяна на версията или модела; иначе тезата се
# ползва повторно. COT_SCHEMA_VERSION се вдига на ръка при промяна на логиката/схемата, която промптът не отразява; освен него
# версията включва хеш на системния текст, промпта и таблиците (виж ai_brief.cot_prompt_version) — промяна на промпта или
# таблицата за знака сама сменя версията. COT_THESES_MAX_AGE_DAYS: при провал на batch се показва СТАРАТА теза на пазара (с
# флаг stale) само ако е най-много толкова дни стара, иначе — празна с причина. FORCE_COT_REGEN=1 регенерира всичко.
COT_THESES_CACHE_FILE = DATA_DIR / "cot_theses_cache.json"
COT_SCHEMA_VERSION = os.getenv("COT_SCHEMA_VERSION", "1")
COT_THESES_MAX_AGE_DAYS = int(os.getenv("COT_THESES_MAX_AGE_DAYS", 8))
COT_THESES_CACHE_KEEP_DAYS = int(os.getenv("COT_THESES_CACHE_KEEP_DAYS", 30))
FORCE_COT_REGEN = os.getenv("FORCE_COT_REGEN", "0") == "1"
# COT: дали работи (пакет 3 т.з) — ценово потвърждение и track record (src/cot_track.py).
# Потвърждение: цената ПРЕСИЧА SMA10 на седмичните затваряния в посоката на contrarian сигнала и пресичането е скорошно (≤ 4 седмици).
# Track record: екстремуми от COT историята (percentile 10/90 спрямо до 156 предишни седмици, поне 52 предишни) и доходността 2/4/8 седмици
# по-късно. Цените са Yahoo (седмични затваряния, 5 г.): непрекъснати фючърси (=F) за стоки, лихви и индекси, спот за валути, ^VIX за VIX
# (VIX фючърсите не са на Yahoo — спотът е прокси) и BTC-USD/XRP-USD за крипто (спот вместо CME фючърсите). ENABLE_COT_TRACK=0 го изключва.
ENABLE_COT_TRACK = os.getenv("ENABLE_COT_TRACK", "1") == "1"
COT_SMA_WEEKS = int(os.getenv("COT_SMA_WEEKS", 10))
COT_CONFIRM_LOOKBACK_WEEKS = int(os.getenv("COT_CONFIRM_LOOKBACK_WEEKS", 4))
COT_TRACK_MIN_PRIOR_WEEKS = int(os.getenv("COT_TRACK_MIN_PRIOR_WEEKS", 52))
COT_TRACK_MIN_EPISODES = int(os.getenv("COT_TRACK_MIN_EPISODES", 3))      # под толкова епизода редът е "малка извадка"
COT_PRICE_SYMBOLS = {
    "E-mini S&P 500": "ES=F",
    "Nasdaq-100": "NQ=F",
    "E-mini Russell 2000": "RTY=F",
    "E-mini Dow (DJIA)": "YM=F",
    "VIX Futures": "^VIX",
    "US Dollar Index": "DX-Y.NYB",
    "Euro FX": "EURUSD=X",
    "Japanese Yen": "JPYUSD=X",
    "British Pound": "GBPUSD=X",
    "Swiss Franc": "CHFUSD=X",
    "Canadian Dollar": "CADUSD=X",
    "Australian Dollar": "AUDUSD=X",
    "Mexican Peso": "MXNUSD=X",
    "2-Year Treasury Note": "ZT=F",
    "5-Year Treasury Note": "ZF=F",
    "10-Year Treasury Note": "ZN=F",
    "Ultra Treasury Bond": "UB=F",
    "30-Year Treasury Bond": "ZB=F",
    "Bitcoin Futures (CME)": "BTC-USD",
    "XRP": "XRP-USD",
    "Gold": "GC=F",
    "Silver": "SI=F",
    "Copper": "HG=F",
    "Platinum": "PL=F",
    "Palladium": "PA=F",
    "WTI Crude Oil": "CL=F",
    "Natural Gas": "NG=F",
    "RBOB Gasoline": "RB=F",
    "Heating Oil": "HO=F",
    "Corn": "ZC=F",
    "Soybeans": "ZS=F",
    "Soybean Oil": "ZL=F",
    "Soybean Meal": "ZM=F",
    "Wheat": "ZW=F",
    "Sugar No. 11": "SB=F",
    "Coffee C": "KC=F",
    "Cocoa": "CC=F",
    "Cotton": "CT=F",
    "Lean Hogs": "HE=F",
    "Live Cattle": "LE=F",
}

# значка CLOSED при тикър на COT теза, чиято позиция е затворена до толкова дни назад (виж cot_theses.ticker_badges)
COT_CLOSED_BADGE_DAYS = int(os.getenv("COT_CLOSED_BADGE_DAYS", 14))
COT_CROSS_MAX_TICKERS = int(os.getenv("COT_CROSS_MAX_TICKERS", 3))
COT_MECHANISMS_PER_TICKER = int(os.getenv("COT_MECHANISMS_PER_TICKER", 2))
COT_QUOTE_MAX_CHARS = int(os.getenv("COT_QUOTE_MAX_CHARS", 300))
# само за таблицата с директните тикъри: продукт, който пряко следва инструмента (ETF/ETN/trust); знакът е по "side"
COT_DIRECT_ONLY_TYPES = {"tracks_instrument"}

# Директни тикъри по пазар (пакет 3 т.в) — фиксирана таблица по модела на THESIS_BASKETS; AI пише САМО cross-sector тезите.
# side: "long" = печели, когато цената на инструмента расте (продукт/производител); "short" = обратно (инверсен продукт,
# купувач на суровината). mechanism_type: от COT_MECHANISM_SIGN (за производител: output_price) или "tracks_instrument"
# (ETF/ETN/trust, следващ инструмента). Знакът на типа трябва да съвпада със side (проверява се в теста). "partial": True =
# частична/непълна експозиция (преработвател, диверсифицирана компания) — показва се с бележка. Празен списък + причина =
# няма ликвиден американски тикър с чиста директна експозиция (iPath NIB/BAL/JO/COW и CurrencyShares FXM са делистнати).
# ПРЕДЛОЖЕНИЕ за преглед (проверено срещу Yahoo на 05.10.2026: всички тикъри търгуват; съществуването не е препоръка).
def _d(ticker, side, mtype, note="", partial=False):
    return {"ticker": ticker, "side": side, "mechanism_type": mtype, "note": note, "partial": partial}

# ПРАВИЛО за директната таблица (потребител, 05.10): само ПРИТЕЖАТЕЛИ/ПРОИЗВОДИТЕЛИ на инструмента (side long: tracks_instrument за продукт, който го
# следва, output_price за производител) или ОБРАТНИ продукти (side short + tracks_instrument). Купувачи на суровината, преработватели и потребители
# (input_cost, substitute, consumer_wallet…) НЕ са директни — те са cross тезата с механизъм. Тестът проверява всеки ред срещу това множество.
COT_DIRECT_ALLOWED = {("long", "tracks_instrument"), ("long", "output_price"), ("short", "tracks_instrument")}
COT_DIRECT_TICKERS = {
    "E-mini S&P 500": {"tickers": [_d("SPY", "long", "tracks_instrument", "ETF върху S&P 500"), _d("VOO", "long", "tracks_instrument", "ETF върху S&P 500")]},
    "Nasdaq-100": {"tickers": [_d("QQQ", "long", "tracks_instrument", "ETF върху Nasdaq-100"), _d("QQQM", "long", "tracks_instrument", "ETF върху Nasdaq-100")]},
    "E-mini Russell 2000": {"tickers": [_d("IWM", "long", "tracks_instrument", "ETF върху Russell 2000"), _d("VTWO", "long", "tracks_instrument", "ETF върху Russell 2000")]},
    "E-mini Dow (DJIA)": {"tickers": [_d("DIA", "long", "tracks_instrument", "ETF върху Dow Jones — единственият чист")]},
    "VIX Futures": {"tickers": [_d("VIXY", "long", "tracks_instrument", "краткосрочни VIX фючърси"), _d("VXX", "long", "tracks_instrument", "краткосрочни VIX фючърси (ETN)"),
                                _d("SVXY", "short", "tracks_instrument", "обратен (−0.5×) на краткосрочните VIX фючърси")]},
    "US Dollar Index": {"tickers": [_d("UUP", "long", "tracks_instrument", "бичи фонд върху USD индекса"), _d("UDN", "short", "tracks_instrument", "мечи фонд върху USD индекса")]},
    "Euro FX": {"tickers": [_d("FXE", "long", "tracks_instrument", "trust върху еврото")]},
    "Japanese Yen": {"tickers": [_d("FXY", "long", "tracks_instrument", "trust върху йената")]},
    "British Pound": {"tickers": [_d("FXB", "long", "tracks_instrument", "trust върху паунда")]},
    "Swiss Franc": {"tickers": [_d("FXF", "long", "tracks_instrument", "trust върху швейцарския франк")]},
    "Canadian Dollar": {"tickers": [_d("FXC", "long", "tracks_instrument", "trust върху канадския долар")]},
    "Australian Dollar": {"tickers": [_d("FXA", "long", "tracks_instrument", "trust върху австралийския долар")]},
    "Mexican Peso": {"tickers": [], "empty_reason": "няма листнат американски продукт върху мексиканското песо (FXM е делистнат)"},
    "2-Year Treasury Note": {"tickers": [_d("SHY", "long", "tracks_instrument", "1–3г. съкровищни облигации"), _d("SCHO", "long", "tracks_instrument", "краткосрочни съкровищни облигации")]},
    "5-Year Treasury Note": {"tickers": [_d("IEI", "long", "tracks_instrument", "3–7г. съкровищни облигации"), _d("VGIT", "long", "tracks_instrument", "3–10г. съкровищни облигации")]},
    "10-Year Treasury Note": {"tickers": [_d("IEF", "long", "tracks_instrument", "7–10г. съкровищни облигации"), _d("SCHR", "long", "tracks_instrument", "3–10г. съкровищни облигации")]},
    "Ultra Treasury Bond": {"tickers": [_d("EDV", "long", "tracks_instrument", "облигации с удължена дюрация"), _d("ZROZ", "long", "tracks_instrument", "25+г. нулево-купонни съкровищни облигации")]},
    "30-Year Treasury Bond": {"tickers": [_d("TLT", "long", "tracks_instrument", "20+г. съкровищни облигации"), _d("VGLT", "long", "tracks_instrument", "дългосрочни съкровищни облигации"),
                                          _d("TBF", "short", "tracks_instrument", "обратен (−1×) на 20+г. облигации")]},
    "Bitcoin Futures (CME)": {"tickers": [_d("IBIT", "long", "tracks_instrument", "спот биткойн ETF"), _d("FBTC", "long", "tracks_instrument", "спот биткойн ETF")]},
    "XRP": {"tickers": [_d("GXRP", "long", "tracks_instrument", "XRP trust"), _d("XRP", "long", "tracks_instrument", "Bitwise XRP ETF"), _d("XRPC", "long", "tracks_instrument", "Canary XRP ETF")]},
    "Gold": {"tickers": [_d("GLD", "long", "tracks_instrument", "физическо злато"), _d("IAU", "long", "tracks_instrument", "физическо злато"),
                         _d("NEM", "long", "output_price", "най-големият златодобивач"), _d("AEM", "long", "output_price", "златодобивач")]},
    "Silver": {"tickers": [_d("SLV", "long", "tracks_instrument", "физическо сребро"), _d("SIVR", "long", "tracks_instrument", "физическо сребро"),
                           _d("PAAS", "long", "output_price", "добивач на сребро")]},
    "Copper": {"tickers": [_d("CPER", "long", "tracks_instrument", "фонд върху медни фючърси"), _d("FCX", "long", "output_price", "медодобивач"),
                           _d("SCCO", "long", "output_price", "медодобивач")]},
    "Platinum": {"tickers": [_d("PPLT", "long", "tracks_instrument", "физическа платина"), _d("SBSW", "long", "output_price", "платинови/паладиеви метали (и злато, уран)", partial=True)]},
    "Palladium": {"tickers": [_d("PALL", "long", "tracks_instrument", "физически паладий"), _d("SBSW", "long", "output_price", "платинови/паладиеви метали (и злато, уран)", partial=True)]},
    "WTI Crude Oil": {"tickers": [_d("USO", "long", "tracks_instrument", "фонд върху WTI фючърси"), _d("OXY", "long", "output_price", "добивач на нефт"),
                                  _d("COP", "long", "output_price", "добивач на нефт"), _d("EOG", "long", "output_price", "добивач на нефт и газ")]},
    "Natural Gas": {"tickers": [_d("UNG", "long", "tracks_instrument", "фонд върху фючърси на природен газ"), _d("EQT", "long", "output_price", "производител на природен газ"),
                                _d("AR", "long", "output_price", "производител на природен газ")]},
    "RBOB Gasoline": {"tickers": [_d("UGA", "long", "tracks_instrument", "фонд върху бензинови фючърси"), _d("VLO", "long", "output_price", "рафинер (бензин е основен продукт)", partial=True),
                                  _d("MPC", "long", "output_price", "рафинер (бензин е основен продукт)", partial=True)]},
    "Heating Oil": {"tickers": [_d("VLO", "long", "output_price", "рафинер (дизел/ULSD е основен продукт)", partial=True), _d("MPC", "long", "output_price", "рафинер (дизел/ULSD е основен продукт)", partial=True)]},
    "Corn": {"tickers": [_d("CORN", "long", "tracks_instrument", "фонд върху фючърси на царевица")]},
    "Soybeans": {"tickers": [_d("SOYB", "long", "tracks_instrument", "фонд върху фючърси на соя")]},
    "Soybean Oil": {"tickers": [], "empty_reason": "няма листнат продукт или чист производител върху соевото масло; преработвателите (BG, ADM) са cross тикъри"},
    "Soybean Meal": {"tickers": [], "empty_reason": "няма листнат продукт или чист производител върху соевото брашно; преработвателите (BG, ADM) и потребителите на фураж са cross тикъри"},
    "Wheat": {"tickers": [_d("WEAT", "long", "tracks_instrument", "фонд върху фючърси на пшеница")]},
    "Sugar No. 11": {"tickers": [_d("CANE", "long", "tracks_instrument", "фонд върху фючърси на захар")]},
    "Coffee C": {"tickers": [], "empty_reason": "няма листнат американски продукт върху кафето (iPath JO е делистнат)"},
    "Cocoa": {"tickers": [], "empty_reason": "няма листнат американски продукт върху какаото (iPath NIB е делистнат)"},
    "Cotton": {"tickers": [], "empty_reason": "няма листнат американски продукт върху памука (iPath BAL е делистнат)"},
    "Lean Hogs": {"tickers": [_d("SFD", "long", "output_price", "производител на свинско (разходите за фураж също влияят)", partial=True)]},
    "Live Cattle": {"tickers": [], "empty_reason": "няма листнат продукт или чист производител върху говеждия добитък (COW е делистнат); месопреработвателите (TSN) са cross с input_cost"},
}

# ── MOVE Index (ICE BofA, bond volatility) ────────────────────────────────
MOVE_YELLOW_THRESHOLD = float(os.getenv("MOVE_YELLOW_THRESHOLD", 100))
MOVE_RED_THRESHOLD = float(os.getenv("MOVE_RED_THRESHOLD", 150))
MOVE_SPIKE_WEEKLY_DELTA = float(os.getenv("MOVE_SPIKE_WEEKLY_DELTA", 15))
# ── VIX Term Structure (VIX9D / VIX3M ratio) ──────────────────────────────
VIX_TERM_WARNING_THRESHOLD = float(os.getenv("VIX_TERM_WARNING_THRESHOLD", 1.0))
VIX_TERM_BACKWARDATION_THRESHOLD = float(os.getenv("VIX_TERM_BACKWARDATION_THRESHOLD", 1.1))
# ── IEI/HYG (Credit Spread Proxy) ──────────────────────────────────────────
# FIX 2026-08-25: backtest (Venci) срещу 4 известни кризисни прозореца
# (GFC 2007-08, late-2018 selloff, COVID crash 2020, Aug'24 yen carry
# unwind) потвърди: остър 10-дневен RoC spike прецизно маркира началото на
# credit turbulence, 0 false positives в 4/4 спокойни контролни периода
# (вкл. SVB март 2023). 19-годишен секуларен спад в дъното на ratio-то
# (2.13→1.46) изключва фиксирани абсолютни прагове — percentile/rolling
# подход, same методология като COT модула (виж cot.py: _percentile_rank).
# 504 дни (~2г) е разумен starting point за rolling прозорец — достатъчно
# скорошен спрямо секуларния тренд, достатъчно данни за стабилна
# статистика; всички стойности tunable занапред.
IEI_HYG_LOOKBACK_DAYS = int(os.getenv("IEI_HYG_LOOKBACK_DAYS", 504))
IEI_HYG_LEVEL_PERCENTILE_LOW = float(os.getenv("IEI_HYG_LEVEL_PERCENTILE_LOW", 10))
IEI_HYG_ROC_WINDOW_DAYS = int(os.getenv("IEI_HYG_ROC_WINDOW_DAYS", 10))
IEI_HYG_ROC_SPIKE_PERCENTILE = float(os.getenv("IEI_HYG_ROC_SPIKE_PERCENTILE", 90))
# FIX 2026-10-03 (пакет 2 т.10): хистерезисът държи override (MOVE spike / IEI-HYG spike) при СКРИТ индикатор — скритите дни не
# са спокойни (замразява се streak-ът). Без таван това е безкрайно: ^MOVE беше скрит 22 поредни дни през юли 2026 (27 общо от 78
# брифа), а override, повдигнал режима до Defensive, би стоял толкова, колкото тече повредата на източника. След този брой
# ПОРЕДНИ дни без данни override-ът се ОСВОБОЖДАВА (10-ият пореден скрит ден е първият без override): ред в лога и текст в брифа.
# Ако данните се върнат със спайк, override-ът се вдига наново; ако не — режимът е по броенето.
HYSTERESIS_HIDDEN_RELEASE_DAYS = int(os.getenv("HYSTERESIS_HIDDEN_RELEASE_DAYS", 10))
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
# 2026-10-03 (пакет 2 т.2): Fed Net Liquidity — преработена сметка, САМО информативна (не влиза в броенето).
# Преди: WALCL (ниво в сряда) − RRPONTSYD (дневна) − WTREGEN (СЕДМИЧНА СРЕДНА), а "4-седмичният" сравнителен
# ред беше series[-5] на трите РАЗЛИЧНИ серии — 4 седмици назад за WALCL/TGA, но 5 ДНИ назад за дневната RRP;
# и трите компонента бяха към различни дати. Реален пример, сряда 30.09.2026: TGA ниво в сряда (WDTGAL)
# 984 046 млн срещу седмична средна (WTREGEN) 948 674 млн — 35 млрд разлика, повече от типичната седмична
# промяна. Сега и трите компонента са към ЕДНА И СЪЩА сряда (WALCL и WDTGAL са "Wednesday level"; RRP — на същия
# ден, а при празник — последния работен ден до 4 дни назад), промяната е за NET_LIQ_WINDOW_WEEKS седмици, мъртва
# зона ±NET_LIQ_DEAD_ZONE_PCT% (жълто), а цветът се сменя чак след NET_LIQ_CONFIRM_WEEKS поредни седмици в
# новия цвят. История: FRED_HISTORY_DAYS дни седмични точки (хистерезисът се смята върху тях, без state файл).
NET_LIQ_TGA_SERIES = os.getenv("NET_LIQ_TGA_SERIES", "WDTGAL")        # Treasury General Account: Wednesday Level
NET_LIQ_WINDOW_WEEKS = int(os.getenv("NET_LIQ_WINDOW_WEEKS", 4))
NET_LIQ_DEAD_ZONE_PCT = float(os.getenv("NET_LIQ_DEAD_ZONE_PCT", 1.0))
NET_LIQ_CONFIRM_WEEKS = int(os.getenv("NET_LIQ_CONFIRM_WEEKS", 2))
NET_LIQ_HISTORY_DAYS = int(os.getenv("NET_LIQ_HISTORY_DAYS", 300))
# RRPONTSYD е ДНЕВНА (работни дни) компонента — same клас серия като VIX/MOVE
# (публикува се всеки работен ден), затова reuse-ва STALENESS_THRESHOLD_DAYS
# директно, не нужна отделна константа.

# ── Основна инфлация · Dallas Fed Trimmed Mean PCE (2026-09-27) ──────────
# Информативна карта в зоната на термометъра (като Distribution Days) — НЕ
# влиза в броенето зелени/жълти/червени и НЕ влияе на режима. Подава се на
# макро брифа като котва за твърдения за "инфлационен натиск".
ENABLE_CORE_INFLATION = os.getenv("ENABLE_CORE_INFLATION", "1") == "1"
CORE_PCE_SERIES = "PCETRIM12M159SFRBDAL"   # месечна, % г/г
# FIX 2026-09-28: посока = средно за последните N месеца срещу предходните N,
# не една точка (юли срещу май сравняваше с локален връх: 2.43 при плоска
# серия 2.36/2.35/2.43/2.26/2.28). Под ±FLAT_PP → "стабилна". Измерено върху
# цялата серия (578 месеца от 1978): ±0.10 пп дава 48% стабилна (53% от 2015);
# ±0.05 е в шума на закръглянето до 2 знака, ±0.15 пропуска спада 11.2025.
CORE_PCE_AVG_MONTHS = int(os.getenv("CORE_PCE_AVG_MONTHS", 3))
CORE_PCE_FLAT_PP = float(os.getenv("CORE_PCE_FLAT_PP", 0.10))
# Месечна серия с ~1 месец закъснение — дневният 3-дневен праг би я крил
# постоянно. Възрастта се мери от КРАЯ на отчетния месец (FRED датира
# наблюдението с 1-во число): юли (01.07) на 29.09 е 60 дни от 31.07, но 90
# от 01.07 — нормален цикъл точно преди новото издание, не застой.
CORE_PCE_STALENESS_DAYS = int(os.getenv("CORE_PCE_STALENESS_DAYS", 75))

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
# FIX 2026-09-28: 20–40% вече е жълто "слаба/тясна ширина", не зелено
# "здравословна" — 67% (17.08) → 22.5% (28.09) при SPY близо до върха беше
# показвано като здравословно. Проверено върху 14-те дни под 40% (09–28.09):
# режимът по броене не се сменя нито веднъж (Offensive иска ≥4 зелени, 0 червени).
BREADTH_WEAK_THRESHOLD = float(os.getenv("BREADTH_WEAK_THRESHOLD", 40.0))
# Бележка за разминаване: ширина под BREADTH_WEAK_THRESHOLD, докато SPY е на
# ≤ този % от 52-седмичния си връх. Измерено 14.08–28.09 (цялата наличната
# breadth история): SPY беше на ≤3% от върха в 13 от 14-те дни под 40%.
SPY_NEAR_HIGH_PCT = float(os.getenv("SPY_NEAR_HIGH_PCT", 3.0))

# ── SEC Form 4 Insider Buying (officers CEO/CFO/President/COO, open market) ──
ENABLE_INSIDER_BUYING = os.getenv("ENABLE_INSIDER_BUYING", "1") == "1"
INSIDER_MIN_VALUE = float(os.getenv("INSIDER_MIN_VALUE", 100_000))
INSIDER_CLUSTER_WINDOW_DAYS = int(os.getenv("INSIDER_CLUSTER_WINDOW_DAYS", 14))
INSIDER_CLUSTER_MIN_COUNT = int(os.getenv("INSIDER_CLUSTER_MIN_COUNT", 3))
# Пакет 4б т.в: списъкът "Insider Buying" отпадна — маркер INS✓ върху НАШИ кандидати и позиции. Тегли се само за тях (не за целия S&P500+NDX100);
# таван на тикърите на едно извикване (всеки тикър = 1 заявка към SEC submissions + XML на скорошните Form 4).
INSIDER_MARKER_MAX_TICKERS = int(os.getenv("INSIDER_MARKER_MAX_TICKERS", 60))

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
# 2026-10-05 (допълнение към пакет 2): червени distribution days (max(SPY, QQQ) >= DISTRIBUTION_DAYS_RED) → режимът е най-много
# Defensive, никога Offensive (с ясна причина в regime_reason; Cash и Defensive не се пипат). Преди това сигналът беше само
# информативна карта до термометъра: на 16–24.09 имаше 6 Offensive дни с червени distribution days.
DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE = os.getenv("DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE", "1") == "1"
# Асиметричен хистерезис на блока: влиза веднага при първия червен ден, пада след толкова ПОРЕДНИ нечервени дни (жълт/зелен).
# Без него броят около прага (8↔9) връщаше Offensive за един ден между два червени (25.09 червено, 28.09 жълто, 29.09 червено).
DISTRIBUTION_DAYS_RELEASE_NONRED_DAYS = int(os.getenv("DISTRIBUTION_DAYS_RELEASE_NONRED_DAYS", 2))

# ── Track Record / Backtest (Action препоръки: target/stop резолюция) ─────
ENABLE_BACKTEST = os.getenv("ENABLE_BACKTEST", "1") == "1"
BACKTEST_MAX_HOLD_WEEKS = int(os.getenv("BACKTEST_MAX_HOLD_WEEKS", 16))
# Санитарна проверка при автоматична split корекция (backtest._apply_split_adjustment):
# коригираният entry трябва да е в тази граница от split-коригирания Close на
# entry деня в историята на yfinance — иначе историята още не е коригирана и
# корекцията би била грешна. Калибрирано срещу 48 записа без сплит (23.09):
# натуралното разминаване entry↔Close е медиана 1.76%, p99 6.52%, макс 8.21%
# (entry е средата на плановата зона, не Close-ът). Най-малкият реален сплит
# (5:4) дава 25%. 15% стои по средата на празнината 8.2%→25% — ~1.8× над
# най-лошия наблюдаван шум, и под най-малкия реален сплит.
SPLIT_SANITY_MAX_DEV = float(os.getenv("SPLIT_SANITY_MAX_DEV", 0.15))

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
# Пакет 4б т.е (06.10.2026): ХИСТЕРЕЗИС — вход само при close ≥ линията × (1 + ENTRY%); кандидатът остава, докато close ≥ линията × (1 − EXIT%). Събитието (дата, линия, тип)
# се пази в data/glb_state.json и оцелява при смяна на месеца. Преди: close > линията с точно 0% буфер и преизчисляване всеки ден от месечната серия → граничен тикър мигаше
# всеки ден, а в първия ден на месеца линията се прескачаше от последния месечен close и ВСИЧКИ кандидати на месеца изчезваха (реално 01.09→02.09: 18 от 18).
GLB_HYSTERESIS = os.getenv("GLB_HYSTERESIS", "1") == "1"
GLB_ENTRY_MARGIN_PCT = float(os.getenv("GLB_ENTRY_MARGIN_PCT", 1.0))
GLB_EXIT_MARGIN_PCT = float(os.getenv("GLB_EXIT_MARGIN_PCT", 3.0))
GLB_STATE_FILE = DATA_DIR / "glb_state.json"


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

# ══════════════════════════════════════════════════════════════════════════
# Short/Stage 4 Screener — Модул 1, Short/Reversal тема (2026-08-2x)
# ══════════════════════════════════════════════════════════════════════════
# Sector-first подход: НЕ "огледало на CANSLIM" сред качествени компании
# (рядко/трудно се shortват) — вместо това: (1) потвърдена, устойчива
# секторна слабост → (2) universe expansion в рамките на сектора (small/
# mid-cap, не top-tier институционални) → (3) survival-risk + Stage 4
# технически филтър. Пълен feasibility/backtest trail: coal 2014-2016
# (persistence gate + Stage 4 technical mirror потвърдени directamente на
# реални цени — ARLP/CNX proxy, bankrupt small-caps нямат данни в yfinance)
# + 2023-2025 smoke test (TAN/XLRE потвърдени срещу documented real-world
# events, вкл. SPWR Chapter 11 август 2024, хванат от universe expansion-а).
ENABLE_SHORT_SCREENER = os.getenv("ENABLE_SHORT_SCREENER", "1") == "1"

# ── Sector persistence gate (sector_layer.py: laggard_sectors()) ─────────
# FIX 2026-08-2x: наивен single-day "chg_4w<0 AND chg_12w<0" дава false
# positives от еднодневен шум (потвърдено на живо: ITA/Индустрия both-neg
# само 1-2 от последните 20 дни — чист шум, докато XLU/TAN устойчиво
# 16-20/20). Coal 2014-16 backtest потвърди: gate-ът правилно хваща началото
# на устойчивата слабост (Сеп 2014, ~10-11 месеца ПРЕДИ първите bankruptcy
# filings), но естествено губи чувствителност след пълен колапс (rate-of-
# change метрика, reference точките вече дълбоко депресирани) — приемливо,
# по това време е твърде късно за нов short anyway.
SECTOR_PERSISTENCE_WINDOW_DAYS = int(os.getenv("SECTOR_PERSISTENCE_WINDOW_DAYS", 20))
SECTOR_PERSISTENCE_MIN_DAYS = int(os.getenv("SECTOR_PERSISTENCE_MIN_DAYS", 15))
# 2023-2025 реален daily co-occurrence тест: медиана 5 сектора едновременно
# confirmed-laggard, 90-ти percentile 8, max 12 от 17 — detection gate-ът
# остава широк (полезно за stock-level screening-а), капът е САМО на AI
# extraction стъпката (short_thesis_global_context(), ai_brief.py), там
# където реално се плаща cost/latency цената. Сортирано по severity
# (rs_chg_12w_pct възходящо), same "малко, но значимо" принцип като
# MAX_ACTION_TICKERS/COT whitelist-а.
MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT = int(os.getenv("MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT", 3))
# 2026-10-03 (пакет 4а т.5): AI контекстът "глобално срещу регионално" за short кандидатите е СПРЯН —
# резултатът не се визуализира никъде (short кандидатите не са в dashboard-а), а плащаме до
# MAX_LAGGARD_SECTORS_FOR_AI_CONTEXT Claude извиквания на ден. Логиката на short скрийнъра, данните
# (short_candidates в брифа) и short_tracker остават; ENABLE_SHORT_AI_CONTEXT=1 връща извикванията,
# когато има визуализация.
ENABLE_SHORT_AI_CONTEXT = os.getenv("ENABLE_SHORT_AI_CONTEXT", "0") == "1"

# ── Universe expansion (short_screener.py: short_universe()) ─────────────
# yf.EquityQuery/yf.screen() — потвърдено на живо, нулева нова dependency.
# Market cap диапазон: под MIN = micro-cap manipulation/liquidity риск, над
# MAX = "top-tier институционални" (нарочно избягваме — рядко/трудно се
# shortват, виж модул docstring-а). Exchange филтър изключва OTC/чужди
# тикъри — потвърдено необходимо (живия тест без филтър върна ZPHRF/YZCFF/
# WECFF-тип pink-sheet шум).
SHORT_MIN_MARKET_CAP = int(os.getenv("SHORT_MIN_MARKET_CAP", 50_000_000))
SHORT_MAX_MARKET_CAP = int(os.getenv("SHORT_MAX_MARKET_CAP", 2_000_000_000))
SHORT_ALLOWED_EXCHANGES = ["NMS", "NYQ", "NGM"]
SHORT_MIN_PRICE = float(os.getenv("SHORT_MIN_PRICE", 2.0))

# ── Survival-risk критерии (short_screener.py: survival_risk_screen()) ───
# Реалистичен набор, базиран на живо тестван field coverage (Energy sector
# sample): currentRatio/quickRatio/totalDebt/totalCash/freeCashflow/
# operatingCashflow/debtToEquity/epsForward — 6-7 от 7 populated. earnings
# Growth/earningsQuarterlyGrowth — само ~43% populated, same познат Yahoo
# gap като screener.py's CANSLIM филтър — деприоритизирани в полза на
# epsForward vs epsTrailingTwelveMonths (перфектно populated в теста).
SHORT_MAX_CURRENT_RATIO = float(os.getenv("SHORT_MAX_CURRENT_RATIO", 1.0))
SHORT_MAX_QUICK_RATIO = float(os.getenv("SHORT_MAX_QUICK_RATIO", 0.75))
SHORT_MIN_DEBT_TO_EQUITY = float(os.getenv("SHORT_MIN_DEBT_TO_EQUITY", 150))
# N-от-M distress сигнали (6 възможни: weak_current_ratio, weak_quick_ratio,
# high_leverage, declining_revenue, cash_burn, declining_forward_estimates)
# — same "2 от 3 CANSLIM критерия, не твърд AND" философия като screener.py
# fundamental_screen() (Yahoo данните са непълни, единичен твърд праг би
# убил всичко ИЛИ пропуснал реален риск). Калибрирано срещу живия 2023-2025
# тест — SOC (currentRatio=0.24, FCF=-$490M, ROE=-100%) мина ясно с margin,
# "здравите изключения" като SHLS/MAIN/PSEC не минават.
SHORT_MIN_DISTRESS_SIGNALS = int(os.getenv("SHORT_MIN_DISTRESS_SIGNALS", 3))
# FIX 2026-08-2x: mortgage REITs (потвърдено: TWO currentRatio=0.22, ORC=0.12)
# структурно ВИНАГИ показват "разорителен" liquidity ratio — borrow-short-
# buy-MBS е нормалният им бизнес модел, не distress сигнал. Тесен, verified
# exclude (точен industry string match) — само за liquidity сигналите
# (weak_current_ratio/weak_quick_ratio), не за целия ticker. BDCs показват
# същия структурен проблем за НЯКОИ имена (ARCC currentRatio=0.61), но НЯМАТ
# чист отделен industry tag (лепени под generic "Asset Management" заедно
# със здрави имена като MAIN/PSEC) — не могат чисто да се exclude-нат по
# same механизъм; N-от-M изискването по-горе е основната защита за тях.
SHORT_LEVERAGE_EXEMPT_INDUSTRIES = ["REIT - Mortgage"]

MAX_SHORT_CANDIDATES = int(os.getenv("MAX_SHORT_CANDIDATES", 5))  # mirror на MAX_ACTION_TICKERS

# ── short_tracker.py: _risk_plan() risk/entry guard ───────────────────────
# FIX 2026-08-28 (първи реален production run): CABO (risk/entry=72%)
# произведе target_1=-$9.95 — механично невъзможна отрицателна цена.
# SSTK (risk/entry=45%, target_1=$0.53) потвърди, че чист "target_1 < 0"
# guard не стига — подозрително близо до нула, не буквално невалидно.
# Реалните "здрави" кандидати от СЪЩИЯ run клъстерираха 7-15% risk/entry
# (JKS 7.6%, HE 11.7%, GDEV 11.8%, PLAY 14.5%) — ясна пропаст до
# проблемните 45%/72%, без нищо по средата. 30% седи комфортно над
# здравия клъстер, далеч под проблемния — виж short_tracker._risk_plan()
# за пълния rationale защо guard-ваме на risk/entry ниво (root cause), не
# само target_1 след факта.
SHORT_MAX_RISK_PCT_OF_ENTRY = float(os.getenv("SHORT_MAX_RISK_PCT_OF_ENTRY", 0.30))

# ── short_tracker.py (prospective, независим от backtest_tracker.json) ───
# FIX 2026-08-2x: bankruptcy-filing-aware exit логика НЕ е implementирана —
# нямаме надежден, безплатен data source за programmatic Chapter-11-filing
# detection (yfinance няма structured поле; SEC EDGAR 8-K Item 1.03 full-
# text search е неверифициран нов data source lift, извън обхвата сега).
# Потвърден, документиран риск (SPWR: Chapter 11 05.08.2024, последван от
# значителен post-filing price spike авг-сеп 2024 — класически post-
# bankruptcy спекулативна volatility, не индикация за грешна теза) —
# short_tracker.py explicit флагва extreme post-entry move/volume спайкове
# като "unusual_move_disclosure" бележка, вместо тихо да ги третира като
# чист stop-loss. Generic extreme-move detector (mirroring gap-day handling
# в backtest.py) остава explicit future scope item, не в тази версия.
#
# Калибрирано directamente срещу реалния SPWR случай (виж
# short_tracker._unusual_move_note): първоначален дизайн изискваше move И
# volume едновременно (25%/3.0×, AND) — тествано на живо, НЕ сработи.
# SPWR вече е бил heavily-traded distressed stock МЕСЕЦИ преди filing-а
# (pre-entry 50-дневен baseline ~3.2M акции/ден) — самият filing ден показа
# volume ПОД този вече-повишен baseline (0.23×), докато price move-ът
# (+13%) беше ясно значим. Сменено на OR (единичен силен сигнал достатъчен)
# + понижени прагове (10%/1.5×) — потвърдено на живо: SPWR case вече се
# хваща коректно, обикновен (не-екстремен) JKS stop case остава без
# disclosure (false-positive контрол минат).
SHORT_EXTREME_MOVE_PCT = float(os.getenv("SHORT_EXTREME_MOVE_PCT", 10.0))
SHORT_EXTREME_VOLUME_MULT = float(os.getenv("SHORT_EXTREME_VOLUME_MULT", 1.5))
