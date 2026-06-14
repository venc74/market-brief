# Market Brief v2 — какво е добавено и как се прилага

Надстройката е **additive**. Долните файлове са drop-in замени/добавки върху работещото v1 repo
`venc74/market-brief`. Не са пипани: `screener.py`, `sizing.py`, `ai_brief.py`, `sector_layer.py`,
`emailer.py`, `README.md`, `test_pipeline.py`.

## 3 разминавания спрямо spec-а (важно)

1. **Няма `templates/email.html`.** Имейлът се генерира inline в `src/render.py` (`render_email`).
   Encoding fix-ът (Секция 2.1) и новите имейл секции отидоха там — добавен е `<head>` с
   `<meta charset="UTF-8">` + `Content-Type` мета.
2. **`templates/dashboard.html` всъщност е `dashboard.html.j2`.** Всички нови раздели + календарът
   са в него; `docs/index.html` е резултатът от рендера му, не се пипа ръчно.
3. **GitHub Pages сервира от `/docs`, значи `data/*.json` в root-а НЕ е достъпен по HTTP** — календарът
   нямаше да работи както е описан. Решено: `render.py` сега огледалва всеки ден в `docs/data/<дата>.json`
   и гради `docs/data/index.json` манифест от `docs/archive/*.html`. Календарът отваря архивната HTML
   страница в iframe (същият layout, защото е същият рендер).

## Нови файлове

| Файл | Какво прави |
|---|---|
| `src/magic_formula.py` | Greenblatt EY+ROC върху независим референтен универс (`config.MAGIC_FORMULA_UNIVERSE`), дневен кеш, маркер `MF✓`. |
| `src/borrow_data.py` | Borrow rate от iborrowdesk JSON API → ред в Short Interest секцията. |
| `src/unusual_options.py` | Unusual options volume от Market Chameleon, маркер `UOV✓`, нов dashboard раздел. |
| `src/splits_calendar.py` | Предстоящи сплитове от TipRanks (API + HTML fallback), маркер `SPLIT✓` + катализатор. |
| `src/dataroma.py` | Значими superinvestor покупки (13F) от dataroma над $10M, маркер `SI✓`, раздел „Superinvestor Moves". |
| `docs/tax.html` | Самостоятелен данъчен калкулатор (DE Abgeltungsteuer + BG), FIFO, ECB auto-fetch, CSV/PDF експорт. |

## Модифицирани файлове

| Файл | Промяна |
|---|---|
| `config.py` | + v2 блок: MF универс/top_n, 6 тематични кошници, NAAIM прозорец, `ENABLE_*` toggle-и. |
| `src/macro_layer.py` | + `thesis_monitor()` (Секция 5) — оценява кои тези са активни спрямо макрото. |
| `src/thermometer.py` | + `naaim_history()` (Секция 6) — 52-седмична поредица за chart. |
| `src/enrich.py` | + интеграция на 4-те източника: маркери MF✓/UOV✓/SPLIT✓ + borrow; `inject_split_catalysts()`. |
| `src/main.py` | + извиква thesis_monitor, новите fetch-ове и split-катализаторите в правилния ред; новите блокове в `brief`. |
| `src/render.py` | + подава новите template променливи; `_publish_history()` mirror; encoding fix + signals секция в имейла. |
| `templates/dashboard.html.j2` | + маркери по картите, borrow ред, раздели Thesis/Unusual/Splits/NAAIM chart, исторически календар + JS. |
| `requirements.txt` | + `beautifulsoup4`, `html5lib` (fallback парсъри за read_html). |
| `.github/workflows/daily_brief.yml` | `checkout@v4 → @v4.2.2`, `setup-python@v5 → @v5.3.0` (Секция 2.2). |

## Деплой стъпки

1. Копирай файловете на същите пътища, commit.
2. `pip install -r requirements.txt` (локално) — в CI се случва само̀.
3. Първото пускане ще създаде `docs/data/index.json`; календарът ще вижда всички дни от `docs/archive/`.
4. `docs/tax.html` е достъпен на `https://<username>.github.io/<repo>/tax.html` — линкни го от dashboard-а ако искаш.
5. Toggle при проблем с източник: env `ENABLE_MAGIC_FORMULA=0` и т.н. — брифът пада обратно тихо (graceful degradation).

## ⚠ dataroma кодове — верифицирай

`config.DATAROMA_MANAGERS` съдържа кодовете на мениджърите от URL-а на dataroma
(`/m/holdings.php?m=КОД`). Не можах да ги тествам срещу живия сайт (sandbox-ът блокира
dataroma.com), затова **отвори всеки и потвърди кода в адреса**. При грешен код мениджърът
тихо се пропуска. Ако всички per-manager страници върнат нищо, има fallback към `allact.php`,
който не изисква кодове (но няма $ стойности → филтърът работи само където стойност е налична).
Parsing логиката е unit-тествана върху синтетичен dataroma HTML и минава.

## CSV формат за tax.html

```
date,ticker,action,shares,price,currency,exchange_rate,eu_exempt
2026-01-15,AAPL,buy,10,185.50,USD,0.92,false
2026-03-20,AAPL,sell,15,210.00,USD,,false      ← празен rate → бутон „ECB курс"
2026-04-12,SAP,sell,20,162.50,EUR,1,true        ← EU/EEA → 0% в BG
2026-03-01,MSFT,dividend,30,0.83,USD,0.90,false  ← дивидент
```
`exchange_rate` = EUR за 1 единица от валутата (празно → авто от frankfurter.app по датата).

---

# v2.1 — поправки + news_aggregator (тази итерация)

Базирано върху v2 файловете (не пренаписани). Промени:

## Поправки
1. **Magic Formula** — `magic_formula.py` `_metrics()` връща и `name`; `main.py` подава
   `magic_formula.build_ranked(top_n=10)` като `brief["magic_formula_top"]`; нова dashboard
   секция **„Magic Formula Top 10 Today"** (независима таблица; ред със зелено + `MF✓` когато
   тикърът е и в CANSLIM скринера). Маркерът `MF✓` по картите остава.
2. **iborrowdesk** — нова dashboard секция **„Borrow Rate · търсене на тикър"**: input + Enter,
   чист JS вика `iborrowdesk.com/api/ticker/<SYM>` директно от браузъра, показва Borrow Rate,
   налични акции, тренд и история на наличието. Без backend. ⚠ виж бележката за CORS долу.
3. **Unusual Options** — `unusual_options.py` пренаписан: **Tradier API primary** (option volume
   vs open interest върху `config.UNUSUAL_OPTIONS_UNIVERSE`), **Market Chameleon fallback**.
   Секцията преименувана на **„Unusual Options Yesterday"**. Нов env `TRADIER_API_KEY`.
4. **Superinvestor 13F** — секцията преименувана на **„Superinvestor Positions — Last 13F"**,
   показва само **топ 5** по стойност (`superinvestor_moves[:5]`). `SI✓` маркерите остават.
5. **TipRanks splits** — добавен трети fallback **stockanalysis.com/actions/splits/** (Път 3),
   ако TipRanks API + HTML се провалят.
6. **Encoding** — `templates/email.html` НЕ съществува (имейлът е inline в `render.py`, вече с
   `<head><meta charset="UTF-8">`). В `emailer.py`: Subject вече се енкодва с `Header(subject,"utf-8")`
   (RFC2047) — това оправя нечетимата кирилица в ТЕМАТА; SMTP тялото си беше UTF-8 коректно.

## Нов модул
- **`src/news_aggregator.py`** — RSS (Reuters business/world, FT, CNBC) + nitter scrape
  (@unusual_whales, @zerohedge, @elerianm), последни 24ч → Claude филтър (макс 8 новини, всяка с
  едно изречение защо е важна) → dashboard секция **„Значими новини"** преди макро брифа + ред в
  имейла. Graceful: всички източници паднат → секцията се пропуска. Кешира за деня.
  Нова зависимост: `feedparser`. Toggle: `ENABLE_NEWS`, `NEWS_ENABLE_NITTER`.

## ⚠ Две честни бележки (не можах да тествам срещу живите услуги)
- **iborrowdesk CORS**: ако iborrowdesk не връща CORS headers, директният browser fetch ще се
  блокира. Сложил съм fallback през `api.allorigins.win` (публичен CORS reader) — премахни го от
  JS-а ако не искаш трета страна; тогава остава директният опит.
- **Reuters RSS / nitter**: публичните Reuters RSS емисии и nitter инстанциите често са down.
  Кодът е изцяло graceful — пада тихо. FT/CNBC обикновено работят. Сменяй `NITTER_INSTANCES` при нужда.
- **Tradier**: няма готов „unusual" endpoint — смятам vol/OI върху универс. Parsing логиката е
  unit-тествана със синтетичен chain; добави `TRADIER_API_KEY` secret за да е primary, иначе пада на MC.
