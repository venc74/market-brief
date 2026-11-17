"""
17.11.2026 (пакет 1, т. 2г–2д): ритъмът на редките източници (COT — седмичен, 13F — тримесечен; от 21.10.2026) отпадна заедно с двата модула.
Остава само четенето на предишния бриф (сравнението на режима — „Какво промени режима от предишния бриф“). Локално четене на config.DATA_DIR; грешка → None.
"""
import json

import config


def previous_brief(today: str) -> dict | None:
    """Последният бриф ПРЕДИ днешния ден (data/ГГГГ-ММ-ДД.json с дата < today); няма или е нечетим → None."""
    try:
        files = sorted(p for p in config.DATA_DIR.glob("20??-??-??.json") if p.stem < str(today)[:10])
        return json.loads(files[-1].read_text(encoding="utf-8")) if files else None
    except Exception as e:
        print(f"[data_rhythm] предишният бриф не се прочете: {type(e).__name__}: {e}")
        return None
