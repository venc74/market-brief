"""
Мрежови помощни функции — споделени между модулите, правещи yfinance .info
заявки (ai_brief.py, magic_formula.py, screener.py). Единствена цел: timeout
guard около бавни/увиснали Yahoo заявки (виж fetch_with_timeout по-долу).
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeoutError

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


def fetch_with_timeout(fn, *args, timeout: float | None = None, **kwargs):
    """
    FIX 2026-08-02 (timeout guard находка): обвива произволна функция (типично
    достъп до yf.Ticker(sym).info) с explicit timeout, вместо да разчита на
    default поведението на requests/yfinance.

    ВАЖНО, потвърдено с реалния инсталиран yfinance (1.5.2, data.py):
    самата библиотека ВЕЧЕ слага собствен default timeout=30s на всяко HTTP
    извикване вътрешно (get_raw_json(..., timeout=30), нито един call site в
    quote.py го override-ва) — това НЕ е буквално "unbounded hang", както
    първоначалната хипотеза предполагаше. Проверено е и че requests.Session()
    + HTTPAdapter НЕ работи като fix тук: explicit timeout= kwarg на всяко
    session.get() извикване винаги бие каквото и да е настроено на самия
    session/adapter в requests библиотеката — първата хипотезирана посока
    (session adapter) е технически нежизнеспособна с текущата yfinance версия.

    Остатъчният реален риск: 30s е достатъчно дълго, че систематично забавен
    Yahoo (не единичен тикър) да натрупа минути закъснение в secuential scan
    на десетки тикъри (screener universe, magic_formula, COT proxy имена).
    Тази обвивка бои ЧАКАНЕТО на извикващия код до `timeout` секунди — НЕ
    убива физически заявката (Python threads не могат forcibly да бъдат
    terminate-нати); "изоставената" заявка продължава в background до
    собствения си 30s yfinance timeout. Потвърдено емпирично: с `with
    ThreadPoolExecutor()` __exit__ вика shutdown(wait=True) по подразбиране и
    БЛОКИРА до пълния 30s независимо от timeout-а на .result() — затова тук
    НЕ ползваме `with`, а изричен shutdown(wait=False), за да се върнем
    реално след `timeout` секунди, не да чакаме мълчаливо отдолу.

    За еднократни бавни тикъри изоставената нишка е безобидна (приключва сама
    и се garbage-collect-ва) — целта е pipeline-ът да не Я чака, не да я
    прекъсне физически.

    Връща None САМО при timeout. Друго изключение от `fn` (напр. реална
    HTTPError) пропагира нормално през future.result() — не се гълта тук,
    хваща се от съществуващия по-горен try/except във всеки от трите call
    site-а, същия graceful fallback, който вече имаше преди тази поправка.
    """
    timeout = timeout if timeout is not None else config.YF_INFO_TIMEOUT_SEC
    ex = ThreadPoolExecutor(max_workers=1)
    future = ex.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except _FutureTimeoutError:
        label = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", str(fn))
        print(f"[net_utils] {label}: timeout след {timeout}s — продължавам без резултат")
        return None
    finally:
        ex.shutdown(wait=False)
