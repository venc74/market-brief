# Персонален AI Инвестиционен Бриф

Автоматизирана система за ежедневен пазарен анализ и суинг търговия по spec v1.0.
Всеки работен ден в **07:30 CET** събира макро контекст, измерва пазарния режим,
скринира акции по Weinstein + CANSLIM критерии, синтезира бриф през Claude API
и доставя имейл + dashboard на GitHub Pages.

## Архитектура

```
GitHub Actions (cron 07:30 Berlin, DST-aware)
        │
        ▼
src/main.py ─── Слой 1: macro_layer.py    (FRED, NewsAPI, DXY/VIX/gold/oil)
        │   ─── Термометър: thermometer.py (SPY, VIX, NAAIM, P/C, 2s10s, Net Liquidity)
        │   ─── Слой 2: sector_layer.py    (RS ротация на 16 секторни ETF-а vs SPY)
        │   ─── Слой 3: screener.py        (S&P500+NDX+MidCap400 → Stage 2 → CANSLIM)
        │   ─── enrich.py                  (earnings, опции IV/IVR, short interest)
        │   ─── ai_brief.py                (Claude API: макро бриф + per-ticker карти)
        │   ─── sizing.py                  (1% риск, 2:1 R/R, Defensive ×0.5)
        │   ─── render.py                  (dashboard HTML + email HTML)
        │   ─── emailer.py                 (Gmail SMTP / SendGrid)
        ▼
docs/index.html (GitHub Pages) + data/YYYY-MM-DD.json (история за backtest)
```

## Setup — 7 стъпки

1. **Репо.** Създай GitHub repo, push-ни този код.

2. **GitHub Pages.** Settings → Pages → Source: *Deploy from a branch* →
   branch `main`, folder `/docs`. URL-ът става `https://USERNAME.github.io/REPO/`.

3. **API ключове** (Settings → Secrets and variables → Actions → *Secrets*):
   - `ANTHROPIC_API_KEY` — console.anthropic.com
   - `FRED_API_KEY` — безплатен, fred.stlouisfed.org/docs/api/api_key.html
   - `GMAIL_USER` + `GMAIL_APP_PASSWORD` — myaccount.google.com/apppasswords (изисква 2FA)
   - `EMAIL_TO` — къде да пристига брифът
   - `NEWS_API_KEY` — опционален (newsapi.org free tier); без него макро брифът
     работи само с FRED + пазарни данни

4. **Variables** (същото меню → *Variables*):
   - `DASHBOARD_URL` = URL-ът от стъпка 2
   - `PORTFOLIO_SIZE` = 100000 (или твоята стойност)
   - `RISK_PER_TRADE_PCT` = 1.0

5. **Workflow permissions.** Settings → Actions → General →
   Workflow permissions → *Read and write* (за commit на docs/ и data/).

6. **Тест.** Actions → Daily Investment Brief → *Run workflow*.
   Първото пускане отнема ~15-25 мин (скринингът тегли 2 години история
   за ~900 тикъра).

7. **Локален тест без API-та:** `python test_pipeline.py` — валидира
   правилата, sizing-а и рендера с мок данни.

## Вградени правила (Секция 8 от спека)

| Правило | Къде живее |
|---|---|
| Макс 5 Action тикъра | `config.MAX_ACTION_TICKERS` + `main.apply_hard_rules` |
| Earnings blackout 5 раб. дни | `enrich.earnings_info` + `ai_brief.merge_narratives` |
| VIX > 30 → Defensive, sizing ×0.5 | `thermometer.build_thermometer` |
| Макс 2 акции/сектор | `main.apply_hard_rules` |
| Цена ≥ $10, mcap ≥ $500M | `screener` |
| Задължителен дисклеймер | dashboard footer + email footer |

Твърдите правила се прилагат от **кода след AI класификацията** — моделът
предлага, кодът решава.

## Бележки по данните

- **IV Rank** изисква година IV история, която никой безплатен API не дава.
  Системата си я гради сама: всеки ден записва ATM IV в `data/iv_history.json`
  и изчислява IVR от наличния прозорец, маркиран като `partial (N дни)` докато
  не натрупа 200+ записа. Алтернатива: Tradier API ключ (има sandbox tier).
- **NAAIM** се чете от публичния CSV на naaim.org — ако форматът им се промени,
  индикаторът деградира до "няма данни" без да чупи брифа.
- **Пазарният P/C** е апроксимация чрез SPY опционната верига; CBOE total P/C
  изисква платен фийд.
- **Short interest** идва от Yahoo (`shortPercentOfFloat`, `shortRatio`) —
  FINRA данните се обновяват двуседмично, така че borrow rate липсва.
  За borrow rate: Ortex (платен) или IBKR API (имаш акаунт — Секция 9 разширение).
- Всеки модул деградира gracefully: липсващ ключ или счупен източник дава
  "няма данни" в съответната карта, не убива брифа.

## Бъдещи разширения (Секция 9)

`data/*.json` вече пази пълните дневни снимки — backtest модулът има
всичко нужно. IBKR alerts, Telegram bot и trailing stop tracking се закачат
на същия `main.py` pipeline като допълнителни стъпки след `render`.

---
*Само за информационни цели. Не е финансов съвет.*
