# Market Brief — Персонален AI Инвестиционен Бриф

## Какво е това
Автоматизирана система за ежедневен pre-market бриф (07:30 CET), достъпна на
`venc74.github.io/market-brief`. Събира макро контекст, измерва пазарен режим
(термометър), скринира акции по Weinstein + CANSLIM, синтезира анализ през
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
   (`naaim_exposure()`) и `cot.py` (`get_extremes()`).
4. **AI извиквания на batch-ове**, не едно голямо извикване с фиксиран
   `max_tokens` — доказан проблем (JSON truncation при много кандидати).
   Виж `ai_brief.py: ticker_narratives()` / `cot_theses()` за модела.
5. **Не разширявай CFTC/CANSLIM/screener универси безразборно.** COT модулът
   изрично има whitelist от ~35 ликвидни пазара (`cot.py: MAJOR_MARKETS`) —
   принципът е "малко, но значимо" пред "всичко налично".
6. Преди да пишеш код — прочети целия релевантен файл. Не гадай структура.

## Структура

```
main.py              — оркестратор: macro → thermometer → sectors → screener
                        → enrich → AI synthesis → hard rules → sizing → render
config.py            — ЦЯЛАТА конфигурация тук, нищо разпръснато из кода
src/macro_layer.py    — FRED, DXY/VIX/gold/oil/MOVE, thesis_monitor()
src/thermometer.py     — 7 индикатора (SPY, VIX, NAAIM, P/C, spread, Net
                        Liquidity, MOVE) + Offensive/Defensive/Cash режим
src/sector_layer.py    — RS ротация 16 секторни ETF-а vs SPY
src/screener.py        — Stage 2 + CANSLIM скрийнър
src/enrich.py           — earnings, опции IV/IVR, short interest, маркери
src/ai_brief.py         — Claude API: macro brief, ticker narratives, COT theses
src/cot.py              — CFTC Commitments of Traders, whitelist 35 пазара
src/sizing.py           — 1% риск, 2:1 R/R, Defensive ×0.5
src/render.py            — dashboard HTML (Jinja2) + email HTML
templates/dashboard.html.j2 — единственият source за docs/index.html
```

## Текущи toggle-и и прагове (config.py)

- `VIX_DEFENSIVE_THRESHOLD = 30` — VIX>30 форсира Defensive
- `MOVE_RED_THRESHOLD = 150`, `MOVE_SPIKE_WEEKLY_DELTA = 15` — институционален
  стрес в колатерала форсира Defensive (аналогично на VIX правилото)
- `COT_PERCENTILE_LOW/HIGH = 10/90` — строги прагове, малко на брой резултати
- `MAX_ACTION_TICKERS = 5`, `MAX_PER_SECTOR = 2`

## Известни особености / история на решенията

- GitHub вграденият Actions scheduler се оказа ненадежден → заменен изцяло с
  cron-job.org external trigger.
- NAAIM основният безплатен API е зад Cloudflare/платен модел от 08/2026 →
  fallback верига с graceful hide.
- "Pages build and deployment" червени run-ове от overlapping deploys са
  безобидни (следващият deploy обикновено успява) — не е сигнал за проблем в
  кода.
- Данните тръгват от commit в `main` → GitHub Pages `/docs` папката сервира
  живия dashboard; `data/*.json` в root-а НЕ е публично достъпен по HTTP,
  затова `render.py` огледалва в `docs/data/`.

## Език

Целият потребителски output (dashboard, имейл, AI narrative) е на български.
Тикъри, технически термини (RS, pivot, IVR) остават на английски. Код
коментарите са на български, следвайки съществуващия стил.
