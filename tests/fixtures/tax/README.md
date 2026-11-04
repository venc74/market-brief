# Синтетични входове за docs/tax_core.js (tax-fixes, 04.11.2026)

ВСИЧКО ТУК Е СИНТЕТИЧНО — измислени сметки (U1111111, B2, B3), тикъри (ACME, SPLT, XWLD, GHOST, LOSSCO, DIVCO, EQETF, OLDCO), суми и курсове. Няма реални лични данни.
IBKR файловете следват подредбата на секциите от Activity Statement CSV, както е описана публично (Header / Data редове по секции); НЕ са проверени с реален отчет.
ecb_rates_synthetic.csv — форматът на eurofxref-hist.csv на ЕЦБ (USD за 1 EUR), с постоянен курс за всяка година: 2020 1.10 · 2021 1.20 · 2022 1.10 · 2023 1.08 · 2024 1.10 ·
2025 1.05 · 2026 1.15; само делнични дни. Очакваните резултати са сметнати на ръка в test_tax_core.py.

revolut_*_synthetic.csv — по публичното описание на CSV отчетите на Revolut (Trading account statement; Crypto account statement); НЕ са проверени с реален отчет.
