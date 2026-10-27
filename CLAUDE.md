# Market Brief — Персонален AI Инвестиционен Бриф

## Какво е това
Автоматизирана система за ежедневен pre-market бриф (07:30 CET), достъпна на
`venc74.github.io/market-brief`. Събира макро контекст, измерва пазарен режим
(термометър), скринира акции по Weinstein / Minervini trend template + CANSLIM, синтезира анализ през
Claude API, рендерира dashboard (GitHub Pages) + имейл.

Пуска се **само** през cron-job.org (external trigger към GitHub Actions
`workflow_dispatch`) — веднъж дневно, в 07:30 Europe/Berlin (часовата зона на задачата в cron-job.org е Europe/Berlin — часът не се мести при смяната
на часа; потвърдено от Венци 15.10.2026). Workflow файлът (`daily_brief.yml`) **няма** `schedule:` тригер нарочно.

Историята на решенията (измервания, поправки и реплеи по дати), подробните описания на модулите и параметрите по пакети — **docs/HISTORY.md** (преместени дословно на 20.10.2026).

## Работни правила (важно — спазвай стриктно)

1. **Никога не прави `git push` без изрично разрешение.** Направи промените
   локално, покажи ми diff-а, изчакай потвърждение, чак тогава push.
2. **Additive подход навсякъде.** Нови модули/функции се добавят, без да се
   пипа съществуваща логика, освен ако изрично не е поискано друго.
3. **Graceful degradation е задължителен стандарт.** Всеки нов source/fetch
   трябва да е в try/except, при провал да връща празен резултат или
   `hide: True` вместо да чупи pipeline-а. Виж примерите в `thermometer.py`
   (`move_index()`) и `cot.py` (`get_extremes()`).
4. **AI извиквания на batch-ове**, не едно голямо извикване с фиксиран
   `max_tokens` — доказан проблем (JSON truncation при много кандидати).
   Виж `ai_brief.py: ticker_narratives()` / `cot_theses()` за модела.
5. **Не разширявай CFTC/CANSLIM/screener универси безразборно.** COT модулът
   изрично има whitelist от 40 ликвидни пазара (`cot.py: MAJOR_MARKETS`, точно име/код) —
   принципът е "малко, но значимо" пред "всичко налично".
6. Преди да пишеш код — прочети целия релевантен файл. Не гадай структура.
7. **Примерен резултат винаги с етикет за произхода на данните.** Когато
   показваш примерно каре, имейл, секция или ред от страницата, изрично
   отбелязвай дали е от **реални данни** (кой бриф/ден, живи данни и кога)
   или от **тестови/изкуствени** входове. Ако примерът смесва двете —
   маркирай всеки ред/стойност поотделно. Причина: два пъти за три дни
   тестов вход беше показан като реален — "BLSH 1:10 · 02.10" в имейла
   (27.09) и "LMT · watchlist" в карето "Контекст" (29.09).
8. **Съхранени credentials (keychain, PAT, токени) — първо питай.** Преди да
   ползваш съхранен credential за действие, за което не е ползван досега
   (напр. git-ов PAT от keychain за GitHub API вместо за `git push`), питай и
   изчакай отговор. Не печатай стойността му. Изключение само ако
   потребителят изрично е поискал самото действие, както на 02.10 при пробата
   с `workflow_dispatch` на `oi_snapshot.yml` — и тогава кажи кой credential
   е ползван и как.
9. **За всеки външен формат (SEC, CFTC, Nasdaq, Yahoo, RSS, …) тестът ползва РЕАЛЕН файл-fixture, не синтетичен.** Ръчно построеният вход кодира нашите предположения, не формата:
   Form 4 парсерът мина синтетичния тест и пропусна `aff10b5One` в 56 от 56 реални подавания; 13F парсерът четеше `sshPrnAmt`, а реалният тег е `sshPrnamt` — синтетичният
   fixture на 4а беше писан със същия грешен таг и броят акции беше 0 за всеки мениджър до 07.10. Реалният файл (с `tests/fixtures/…`, с бележка откъде и кога е свален) е
   основата на теста; синтетичното е само допълнение (изкривена дата, преименуван таг) и се означава като такова.
10. **Брифът е ПУБЛИЧЕН — в репото, в workflow-ите и в публикуваните данни няма размер на сметка, брой акции, риск в долари или други лични числа.** Размерът на позицията се смята САМО в браузъра
   на читателя (`templates/sizing_core.js` + `sizing_ui.js`) от баланс/риск/таван, които стоят само в localStorage на устройството му. Брифът дава нивата (вход, стоп, ADR, предупреждения —
   `src/trade_levels.py`) и публичния режимен фактор `sizing_factor`. `test_no_account_numbers.py` пази това (и че JS не праща нищо никъде).

### Уроци от историята (кратко; подробно — docs/HISTORY.md)

- Yahoo `Close`/`Open`/`High`/`Low`/`Volume` при `auto_adjust=False` са ВЕЧЕ ретроактивно split-коригирани — без ръчна split корекция върху тях. Реплей върху ново изтеглени данни
  се проверява на известен сплит (NVDA 07.06.2024 ≈ $120.89; канарчето `data_canary`): двойното деление надуваше алфата на "GLB по Уиш" 4 пъти.
- Извадка от реален fixture — по вида на записите, не "първите N" (13F: родителят на Pershing беше подал Q1 13F-HR извън първите 8 записа → "+9 млн HHH" беше обхват, не покупка).
- Нова евристика / замяна / филтър — първо честотата на попаденията и фалшивите върху ЦЯЛАТА история на брифовете; поправка само на потвърдена находка.
- Тестовете са без мрежа: `tests/_nonet` спира socket И curl_cffi (yfinance тегли през curl_cffi — до 20.10 заобикаляше защитата).
- Опростяване без промяна на поведението → `tools/replay_offline.py --base REF` (последните ≥ 20 реални брифа, стар ↔ нов код, без мрежа); всяка разлика — обяснена.

## Операции

- Брифът: cron-job.org → `workflow_dispatch` на `daily_brief.yml` (без `schedule:` нарочно — вграденият scheduler на GitHub беше ненадежден); лимит 90 мин.
- OI снимката: отделен job `oi_snapshot.yml` (~16:00 UTC от cron-job.org + 5 резервни `schedule` тригера), собствена concurrency група `oi-snapshot`; подробно — docs/HISTORY.md.
- Записът на опционните данни: отделен job `options_record.yml` (от 27.10) — cron-job.org → `workflow_dispatch` в 09:05 пон–пет, часова зона America/New_York (преди отварянето;
  без `schedule:` нарочно — прозорецът е 25 мин), собствена група `options-record`, качва само `data/options_daily.json`. Сутрешният бриф не записва (`OPTIONS_RECORD_IN_MORNING_RUN = 0`).
- Страницата: GitHub Pages сервира `/docs` от `main`; `data/*.json` не е публичен → `render.py` огледалва в `docs/data/`. Червени "Pages build and deployment" от застъпени deploy-и
  са безобидни. `docs/.nojekyll` (от 20.10): Pages сервира docs/ както е, без Jekyll (страницата не разчита на него — живите файлове бяха байт по байт същите като в репото);
  `docs/HISTORY.md` се вижда като текст. Пази го `test_history_doc.py`.
- Връщане към v1 — `tracker_switch.revert_to_v1()` възстановява точния v1 tracker, v2 записите
  отиват в `data/backtest_tracker_v2_backup_<дата>.json`, методологията става v1:
  ```bash
  .venv/bin/python -c "from src import tracker_switch; print(tracker_switch.revert_to_v1())"
  ```
  Следващият run превключва наново, затова при реално връщане първо задай `TRACK_RECORD_V2=0`
  (default в config.py или env), после revert, после commit на `data/`. Не пипай
  `daily_brief.yml` без нужда — няма `schedule:` нарочно.

## Структура (кратко; подробните описания към 20.10 — docs/HISTORY.md)

```
src/main.py            — оркестратор: календар → свеж бар → macro → thermometer → sectors → screener → enrich → корпоративни действия → AI synthesis
                         → Track Record (ensure v2, резолюция) → hard rules (технически + режимен gate) → GLB / QM / EP → маркери → ingest → render → имейл
config.py              — ЦЯЛАТА конфигурация тук, нищо разпръснато из кода
src/data_rhythm.py     — ритъмът на редките източници: COT цял само след нов отчет, 13F — само при нов 13F (24.10)
src/crypto_news.py     — крипто секцията: Cointelegraph през AI подбор (дословни заглавия), COIN/HOOD/CRCL/BLSH, COT Bitcoin при нов отчет (24.10)
src/options_record.py  — САМО запис на опционните данни (топ 200 + кандидатите от (а)); със самопроверка — непълен ден не влиза в историята (26.10); от 27.10 — options_record.yml, ~09:05 ET
src/steps.py           — обвивката на стъпките в main.run (20.10): step() → ok / частично / провал / пропусната, brief["run_steps"], банер за провал без собствен банер
src/sessions.py        — NYSE сесии и празници — ЕДНО място (20.10); cut_today / complete_bars — без частичния днешен бар
src/macro_layer.py     — FRED, DXY/VIX/gold/oil/MOVE, thesis_monitor()
src/thermometer.py     — 9 индикатора + Offensive/Defensive/Cash; Net Liquidity и SOFR − IORB — САМО информативни; Offensive иска ≥ 6 видими от 8 броени
src/regime_claims.py   — броенето и правилото на режима като готови низове + проверка на твърденията в макро текста; margin() — "Запас до смяна на режима"
src/entry_timing.py    — distribution days (SPY/QQQ) и статусът им (ok / partial / failed)
src/sector_layer.py    — RS ротация на 16 секторни ETF-а vs SPY; src/sector_claims.py — RS фактите и секторната карта от кода
src/series_utils.py    — last_and_week_ago(): седмица назад по ДАТА + NaN guard
src/bar_freshness.py   — предпазител за застоял дневен бар (изчакване до 25 мин; дял на универса със стар бар)
src/data_warnings.py   — банерите за данни (brief["data_warnings"]); src/health_monitor.py — "Здравна проверка" в края на run-а; src/data_canary.py — канарче за split корекцията
src/screener.py        — Weinstein Stage 2 + Minervini trend template + RS rating + CANSLIM; pivot = най-високият High на базата БЕЗ последните 5 бара
src/setup_rules.py     — код-класификация на сетъпа, buy-stop ниво, "валиден до", stop_levels() — общата стоп математика
src/enrich.py          — earnings, short interest, маркери; src/earnings_move.py — отчет в ~20 сесии + очаквано движение от опциите
src/ai_brief.py        — Claude API на batch-ове: macro brief, ticker narratives, COT theses, проверки на прозата; src/news_aggregator.py — дословни заглавия
src/cot.py, cot_theses.py, cot_track.py, cot_opposites.py — COT: whitelist 40 пазара, тези (таблица + механизми), потвърждение от цената, обратен залог
src/thesis_context.py  — каре "Контекст" към тезите
src/oi_snapshot.py     — следобедната OI снимка за нашите тикъри (отделен job); src/unusual_options.py — UOV✓
src/dataroma.py        — 13F (15 мениджъра, SEC EDGAR): Moves, SI✓, Major Exits; src/cusip_map.py — CUSIP → тикър (OpenFIGI); tools/probe_13f.py — диагностика на ръка
src/insider_buying.py  — Form 4 покупки → INS✓ за нашите тикъри
src/qm_breakout.py     — Qullamaggie breakout (механичен, без AI, отделна стратегия); src/qm_ep.py — Episodic Pivot, само наблюдение
src/glb_screener.py    — GLB карти по правилото на Уиш (линия по месечния High) + свежест (≤ 20 сесии, ≤ +10%) и сигналите на книгите "GLB по Уиш" (High) и "наш вариант (close)" (архив от 26.10)
src/corp_actions.py    — корпоративни действия: изключване при съществено отделяне, маркер под прага; ЕДНО теглене на run (_SERIES)
src/spinoff_watch.py   — предстоящо отделяне от EDGAR 8-K за нашите тикъри; от 21.10 и маркер „цел на придобиване (купувач, дата)“ — 8-K т. 1.01, в който подателят е целта;
                         от 26.10 целта е сделка (setup.kind "deal" — без сетъп, план и Action; записите в книгите — етикет "deal")
src/event_label.py     — етикет „събитие/M&A“ върху записите в книгите: скок ≥ 8% при ≥ 3× обем + заглавие за продажба / придобиване (Google News); статистиката — с и без (26.10)
src/watchlist_exits.py — "Излязоха от вчера"; src/names.py — имена за показване
src/sizing.py          — position_plan_v2() (вход, стоп, цел, sizing_factor) — БЕЗ брой акции / сума; src/trade_levels.py — нивата + ADR (формулата е само тук)
templates/sizing_core.js, sizing_ui.js — оразмеряване в браузъра (localStorage на читателя)
src/trade_sim.py       — ЧИСТА симулация на изпълнението (Action / buy-stop, QM, GLB по Уиш); без I/O — ползва се и от реплея
src/backtest.py        — книгите: Action (v2), buystop, qm_breakout, glb_wish — запис, резолюция, обобщения; book_records / latest_by_ticker / book_intervals — ЕДИНСТВЕНИЯТ слой за четене
src/tracker_switch.py  — еднократно превключване v1→v2 (архив), revert_to_v1()
src/render.py          — dashboard (Jinja2) + имейл; templates/dashboard.html.j2 — единственият source за docs/index.html
src/emailer.py         — имейл доставка (Gmail SMTP / SendGrid; един имейл на ден); src/model_selector.py — най-новият sonnet от Models API
src/watchlist_expiry.py — изтичането на regime_gate кандидатите в Watchlist (NYSE сесии); src/watch_monitor.py — ръчно курираните "Наблюдавани тикъри"
src/magic_formula.py   — Magic Formula cross-check (MF✓); src/correlation_check.py — информационен флаг за корелация между Action кандидатите
src/splits_calendar.py — предстоящи сплитове за текущата седмица (Nasdaq); src/net_utils.py — fetch_with_timeout около бавни Yahoo заявки
src/short_screener.py, short_tracker.py — short / Stage 4 скрийнър и книгата му — ЗАМРАЗЕНИ (SHORT_FROZEN)
run_tests.py, test_*.py — всички тестове (python run_tests.py [име ...]); без мрежа, без секрети, без запис в docs/ и data/ (иначе провал); същото пуска tests.yml при push
tools/replay_offline.py, replay_collect.py — офлайн реплей стар ↔ нов код върху реалните брифове
tests/fixtures/        — РЕАЛНИ входове (OHLC, брифове, tracker-и, SEC 13F, OI, Yahoo .info, RSS, …) с бележка откъде и кога; тестовете НЕ четат data/ и НИКОГА не пишат в нея
```

## Основни прагове (config.py — единственият източник)

- `VIX_DEFENSIVE_THRESHOLD = 30` — VIX>30 форсира Defensive
- `MOVE_RED_THRESHOLD = 150`, `MOVE_SPIKE_WEEKLY_DELTA = 15` — институционален
  стрес в колатерала форсира Defensive (аналогично на VIX правилото)
- `IEI_HYG_ROC_SPIKE_PERCENTILE = 90` (10д RoC, 504д rolling прозорец) —
  credit spread spike форсира Defensive, трети независим hard-override
  тригер (виж `thermometer.py: credit_spread_proxy()`)
- `COT_PERCENTILE_LOW/HIGH = 10/90` — строги прагове, малко на брой резултати
- COT тези (`data/cot_theses_cache.json`): ключ (пазар, as_of, посока, версия на промпта, модел); регенерация само при нов ключ
  или `FORCE_COT_REGEN=1`; `COT_THESES_MAX_AGE_DAYS = 8` — максимална възраст на стара теза при провал на batch; при остарели
  COT данни нищо не се регенерира. Директните тикъри са в `COT_DIRECT_TICKERS`, механизмите/знакът — `COT_MECHANISM_SIGN`
  (в config.py); AI връща само механизми, ефектът е на кода
- `DISTRIBUTION_DAYS_RELEASE_NONRED_DAYS = 2` — блокът от distribution days пада след 2 поредни нечервени дни
- `COT_STALE_DAYS = 13` — над това най-новият COT отчет е "стар" (банер в секцията); 6–10 е нормалното,
  13 е празничен петък (06.07.2026)
- `HYSTERESIS_HIDDEN_RELEASE_DAYS = 10` — override, държан от хистерезис при скрит индикатор, се
  освобождава на 10-ия пореден ден без данни (ред в лога + текст в брифа)
- `DISTRIBUTION_DAYS_BLOCKS_OFFENSIVE = 1` — червени distribution days (max(SPY, QQQ) ≥ `DISTRIBUTION_DAYS_RED = 9`)
  ограничават режима до Defensive (`thermometer.apply_distribution_cap`; Cash не се пипа; main смята distribution
  days веднага след термометъра)
- Net Liquidity: `NET_LIQ_WINDOW_WEEKS = 4`, `NET_LIQ_DEAD_ZONE_PCT = 1.0`, `NET_LIQ_CONFIRM_WEEKS = 2`;
  Put/Call SPY: percentile спрямо собствената история, `PUTCALL_PERCENTILE_GREEN/RED = 90/10`
- `MAX_ACTION_TICKERS = 5`, `MAX_PER_SECTOR = 2`
- Сетъп/вход (пакет 1): `PIVOT_BASE_BARS = 65`, `PIVOT_EXCLUDE_LAST_BARS = 5`,
  `BUYABLE_ZONE_MAX_PCT = 5.0` (над това = extended), `BUY_STOP_WINDOW_SESSIONS = 5`
  (сесии, вкл. деня на брифа), `BREAKOUT_VOLUME_MULT = 1.5`. `NYSE_HOLIDAYS` покрива
  2026–2028 (официалният календар на nyse.com, 16.10.2026) и трябва да се допълва (за "валиден до"); `NYSE_EARLY_CLOSES` — ранните затваряния (13:00 ET);
  `ENABLE_MARKET_CLOSED_SKIP = 1` — празник / уикенд → брифът не върви
- Стоп: `STOP_STRUCT_LOOKBACK_BARS = 15`, `STOP_STRUCT_BUFFER_PCT = 1.0` (1% под low-а),
  `STOP_MAX_PCT = 8.0`, `STOP_REJECT_STRUCT_RISK_PCT = 10.0` (над това → Watchlist
  "твърде разтегнато")
- Цел/изтичане: `TARGET_PARTIAL_FRACTION = 0.5` (на 2R = `MIN_REWARD_RISK`),
  `TRAIL_SMA_DAYS = 10`, `BACKTEST_MAX_HOLD_WEEKS = 16` (от ВХОДА, mark-to-market)
- Режим → Action: `REGIME_CASH_BLOCKS_ACTION = 1`,
  `REGIME_DEFENSIVE_REQUIRES_GOOD_TIMING = 1` (причина във Watchlist: `regime_block`,
  не изтича като `regime_gate`)
- Trend template: `TREND_TEMPLATE_ENABLED = 1`, `TT_MA200_RISING_BARS = 21`,
  `TT_MIN_ABOVE_52W_LOW_PCT = 30`, `TT_MAX_BELOW_52W_HIGH_PCT = 25`, `RS_RATING_MIN = 70`
  (перцентил в целия универс; `RS_RATING_WEIGHTS = 40/20/20/20`, `RS_QUARTER_BARS = 63`,
  `RS_RATING_MIN_UNIVERSE = 150` — под него филтърът се пропуска с предупреждение)
- Track Record: `TRACK_RECORD_V2 = 1` — автоматично превключване v1→v2 при първия run
- Останалите (пакет 4б, buy-stop, 13F, Qullamaggie, пакетите от 09–19.10) — в блоковете на config.py; описанията им към 20.10 — docs/HISTORY.md, „Параметри по пакети“.

## Език

Целият потребителски output (dashboard, имейл, AI narrative) е на български.
Тикъри, технически термини (RS, pivot, IVR) остават на английски. Код
коментарите са на български, следвайки съществуващия стил.

Латинските съкращения (AH = after-hours, EP, ADR, MA) се пишат с ЛАТИНСКИ букви, никога с кирилски близнаци (А/Н/Е/Р…) и без смесени думи ("момentum"). В QM кода, шаблона и имейла
го пази `test_qm_language.py` (по кодови точки); останалите файлове с такива думи са в code-queue.
