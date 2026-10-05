# Market Brief — Персонален AI Инвестиционен Бриф

## Какво е това
Автоматизирана система за ежедневен pre-market бриф (07:30 CET), достъпна на
`venc74.github.io/market-brief`. Събира макро контекст, измерва пазарен режим
(термометър), скринира акции по Weinstein / Minervini trend template + CANSLIM, синтезира анализ през
Claude API, рендерира dashboard (GitHub Pages) + имейл.

Пуска се **само** през cron-job.org (external trigger към GitHub Actions
`workflow_dispatch`) — веднъж дневно. Workflow файлът (`daily_brief.yml`)
**няма** `schedule:` тригер нарочно.

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
   изрично има whitelist от ~35 ликвидни пазара (`cot.py: MAJOR_MARKETS`) —
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

## Структура

```
main.py              — оркестратор: macro → thermometer → sectors → screener
                        → enrich → AI synthesis → Track Record (ensure v2,
                        резолюция) → hard rules (технически + режимен gate)
                        → sizing → ingest → render
config.py            — ЦЯЛАТА конфигурация тук, нищо разпръснато из кода
src/macro_layer.py    — FRED, DXY/VIX/gold/oil/MOVE, thesis_monitor()
src/thermometer.py     — 9 индикатора (SPY, VIX, P/C, spread, Net
                        Liquidity, MOVE, VIX Term Structure, Market
                        Breadth, IEI/HYG Credit Spread) +
                        Offensive/Defensive/Cash режим; Net Liquidity е
                        САМО информативен (не се брои), Offensive иска ≥ 6
                        видими от 8 броени
src/sector_layer.py    — RS ротация 16 секторни ETF-а vs SPY
src/series_utils.py    — last_and_week_ago(): седмица назад по ДАТА + NaN guard (VIX, global signals)
src/data_warnings.py   — предупреждения за данни в брифа (паднал Yahoo → brief["data_warnings"])
src/screener.py        — Weinstein Stage 2 + Minervini trend template + RS rating
                        (втори проход върху целия универс) + CANSLIM скрийнър;
                        pivot = най-високият High на базата БЕЗ последните 5 бара
src/setup_rules.py     — код-класификация на сетъпа (confirmed / no_volume /
                        below_pivot / extended / too_wide), buy-stop ниво, "валиден
                        до" в сесии, stop_levels() — общата стоп математика
src/enrich.py           — earnings, short interest, borrow, маркери (MF✓/UOV✓/SPLIT✓/SI✓)
src/ai_brief.py         — Claude API: macro brief, ticker narratives, COT theses
src/cot.py              — CFTC Commitments of Traders, whitelist 35 пазара
src/thesis_context.py   — каре "Контекст" (само данни) към маркираните тези
src/oi_snapshot.py      — следобедна OI снимка за Unusual Options (отделен job)
src/sizing.py           — 1% риск, 2:1 R/R, Defensive ×0.5; position_plan_v2():
                        buy-stop вход, структурен стоп, цел 50% на 2R
src/trade_sim.py        — ЧИСТА симулация на изпълнението (buy-stop, частична
                        продажба, trailing 10DMA, гап изход, mark-to-market
                        изтичане, SPY сравнение); без I/O — ползва се и от реплея
src/backtest.py         — Track Record v2: tracker (pending/open/trailing/…),
                        резолюция през trade_sim, обобщение за dashboard-а
src/tracker_switch.py   — еднократно превключване v1→v2 (архив), revert_to_v1()
src/render.py            — dashboard HTML (Jinja2) + email HTML
templates/dashboard.html.j2 — единственият source за docs/index.html
run_tests.py, test_*.py — пуска всички тестове (python run_tests.py [име ...]); без
                        мрежа, без секрети, без запис в docs/ и data/ (иначе провал);
                        същото пуска .github/workflows/tests.yml при push
tests/fixtures/        — реални входове: OHLC (AMD, TWLO, LNTH, EXEL, SPY), копие на
                        реалния v1 tracker, реални брифове (22.09, 29.06, 02.10, 08.09),
                        OI снимка от 01.10 — тестовете НЕ четат data/ (ротира се) и
                        НИКОГА не пишат в нея (временна директория)
```

## Текущи toggle-и и прагове (config.py)

- `VIX_DEFENSIVE_THRESHOLD = 30` — VIX>30 форсира Defensive
- `MOVE_RED_THRESHOLD = 150`, `MOVE_SPIKE_WEEKLY_DELTA = 15` — институционален
  стрес в колатерала форсира Defensive (аналогично на VIX правилото)
- `IEI_HYG_ROC_SPIKE_PERCENTILE = 90` (10д RoC, 504д rolling прозорец) —
  credit spread spike форсира Defensive, трети независим hard-override
  тригер (виж `thermometer.py: credit_spread_proxy()`)
- `COT_PERCENTILE_LOW/HIGH = 10/90` — строги прагове, малко на брой резултати
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
  2026–2027 и трябва да се допълва (за "валиден до")
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

## Известни особености / история на решенията

- GitHub вграденият Actions scheduler се оказа ненадежден → заменен изцяло с
  cron-job.org external trigger.
- NAAIM Exposure Index беше премахнат изцяло от термометъра (08/2026) —
  основният безплатен API стана платен (Nasdaq Data Link), индикаторът беше
  permanently скрит от седмици, и субективен survey resultat не може реално
  да се замести с изчислен proxy от пазарни данни.
- Unusual Options OI (от 29.09.2026): сутрин в 05:30–05:55 UTC Yahoo връща
  празен/непълен open interest, затова OI идва от отделен следобеден job
  (`.github/workflows/oi_snapshot.yml`, 15:00 UTC пон–пет, с `schedule:` —
  прозорецът е широк и закъснение не вреди) → `data/unusual_options_oi_snapshot.json`.
- "Pages build and deployment" червени run-ове от overlapping deploys са
  безобидни (следващият deploy обикновено успява) — не е сигнал за проблем в
  кода.
- Данните тръгват от commit в `main` → GitHub Pages `/docs` папката сервира
  живия dashboard; `data/*.json` в root-а НЕ е публично достъпен по HTTP,
  затова `render.py` огледалва в `docs/data/`.
- Пакет 1 (03.10.2026) — ядро на сигналите. Преди: pivot = max(High[-65:]) включваше
  сигналния бар, затова close ≤ pivot ВИНАГИ (95 от 97 Action реда под pivot, 2 на него,
  0 над; Entry Timing "good" — недостижим), а Track Record влизаше по средата на
  entry_range без реално изпълнение (фантомни входове; 1 печеливш от 26). Сега:
  • pivot без последните 5 бара; Action само при ПОТВЪРДЕН пробив (close над pivot, до +5%,
    обем ≥ 1.5×, структурен риск ≤ 10%); останалото отива във Watchlist (`technical_gate`)
    с buy-stop ниво — кодът има последната дума над AI класификацията;
  • изпълнение: buy-stop на pivot; първата сесия е деня на брифа (бриф преди отваряне),
    прозорец 5 сесии, вход по max(Open, pivot), над pivot +5% не се гони; без вход →
    `not_triggered` (извън статистиката). R и доходността се мерят от РЕАЛНАТА цена на входа,
    не от сигналния close (той е само за плана на картата);
  • стоп под 15-баровия low (−1%), най-много 8% под входа; 50% на 2R, остатъкът trailing под
    10DMA със запазен стоп; гап през стопа → изход по Open; изтичане след 16 седмици →
    mark-to-market R;
  • режим: Cash → без Action; Defensive → само при Entry Timing "good";
  • Minervini trend template + RS rating ≥ 70, слети със старата Stage 2 проверка.
  Реплей 02.01.2024–01.10.2026 (904 тикъра): НЯМА демонстрирана алфа — промените са за
  коректност и контрол на риска, не обещание за доходност (числата са в коментарите на
  config.py и в commit-ите "Package 1").
- Track Record v1 → v2 (чист старт). При ПЪРВИЯ run с v2 код `tracker_switch.
  ensure_v2_methodology()` (от main.run, преди резолюцията): резолюция на живите v1;
  изтеклите във фаза 1 получават mark-to-market R по Close при изтичането; останалите
  отворени се затварят по последния Close като `v1_closed` (MTM R). Всичко отива в
  `data/backtest_archive_v1.json` (заедно с точно копие на tracker-а преди превключването),
  `data/backtest_tracker.json` остава само с v2 записи, `data/track_record_state.json` пази
  методологията и v1 статистиката. Брифът показва един ред "v1 методология: n=…, win rate …,
  среден R …". OPEN✓, RE-ENTRY и позициите в COT промпта гледат само v2 записи; v1 планове от
  старите snapshot-и не се ingest-ват повторно. Идемпотентно и graceful: без цени →
  отлага за следващия run; срив на всяка стъпка не губи данни (архив → tracker → състояние).
  Новите файлове в `data/` се записват от workflow-а (`git add docs/ data/`).
- Пакет 4а (03.10.2026) — изчистване: махнати са Scion от 13F списъка, секцията High-Conviction
  New Positions (вместо нея маркер SI✓ с мениджър и дата на filing-а), widget-ът Borrow Rate
  (търсене), опционният блок на картите и AI контекстът на short скрийнъра
  (`ENABLE_SHORT_AI_CONTEXT=0`); базата се казва "база X% дълбочина"; Insider/13F показват давност и
  разграничават легитимна нула от провал; Jinja е с autoescape, имейлът escape-ва външния текст;
  13F мащабът хиляди/долари е по дата на филинга + цена/акция.
- Пакет 2 (03.10.2026) — термометър, макро и данни: секторен приоритет (ETF → Yahoo сектор/индустрия,
  маркер SECT✓, само подредба); Net Liquidity с седмични нива към една сряда (WALCL, WDTGAL, RRP),
  4-седмична промяна, мъртва зона ±1%, 2 седмици потвърждение — информативен; Put/Call по собствена
  история (скрит при провал); макро брифът след значимите новини (NewsAPI махнат); доходностите в
  б.п. (`chg_5d_bp`); паднал Yahoo не сваля run-а (`data_warnings`); COT давност; часът е берлински
  (CET/CEST); VIX и global signals с календарен прозорец + NaN guard; освобождаване на хистерезиса.
  Допълнение (05.10): червени distribution days → режимът е най-много Defensive.
- Връщане към v1 — `tracker_switch.revert_to_v1()` възстановява точния v1 tracker, v2 записите
  отиват в `data/backtest_tracker_v2_backup_<дата>.json`, методологията става v1:
  ```bash
  .venv/bin/python -c "from src import tracker_switch; print(tracker_switch.revert_to_v1())"
  ```
  Следващият run превключва наново, затова при реално връщане първо задай `TRACK_RECORD_V2=0`
  (default в config.py или env), после revert, после commit на `data/`. Не пипай
  `daily_brief.yml` без нужда — няма `schedule:` нарочно.

## Език

Целият потребителски output (dashboard, имейл, AI narrative) е на български.
Тикъри, технически термини (RS, pivot, IVR) остават на английски. Код
коментарите са на български, следвайки съществуващия стил.
