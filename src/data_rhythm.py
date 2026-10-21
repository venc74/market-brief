"""
21.10.2026 (етап 4, „ритъм на данните“): източниците с редки отчети се показват изцяло само в първия бриф след нов отчет, а в другите дни — с един ред кога е следващият.
  • COT (CFTC, седмичен): данни към вторника, публикувани в петък в 15:30 ET (21:30 Берлин; 20:30 в седмиците, в които САЩ и ЕС още не са сменили часа заедно).
Чисти функции + едно локално четене на предишния бриф (config.DATA_DIR). Всяка грешка → секцията се показва цяла, както досега (graceful).
"""
import datetime as dt
import json
from zoneinfo import ZoneInfo

import config

_NY, _BERLIN = ZoneInfo("America/New_York"), ZoneInfo("Europe/Berlin")


def previous_brief(today: str) -> dict | None:
    """Последният бриф ПРЕДИ днешния ден (data/ГГГГ-ММ-ДД.json с дата < today); няма или е нечетим → None."""
    try:
        files = sorted(p for p in config.DATA_DIR.glob("20??-??-??.json") if p.stem < str(today)[:10])
        return json.loads(files[-1].read_text(encoding="utf-8")) if files else None
    except Exception as e:
        print(f"[data_rhythm] предишният бриф не се прочете: {type(e).__name__}: {e}")
        return None


def _dm(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}"


def cftc_next_release(as_of: str) -> dict:
    """Следващият седмичен отчет след отчета към as_of: данни към деня 7 дни по-късно, публикувани в петъка след него в 15:30 ET → датата и часът в Берлин."""
    d = dt.date.fromisoformat(as_of) + dt.timedelta(days=7)
    fri = d + dt.timedelta(days=(4 - d.weekday()) % 7)
    t = dt.datetime(fri.year, fri.month, fri.day, 15, 30, tzinfo=_NY).astimezone(_BERLIN)
    holiday = fri.isoformat() in config.NYSE_HOLIDAYS                                # петък-празник (25.12.2026, 01.01.2027) — CFTC мести отчета; точната дата е в графика ѝ
    return {"next_as_of": d.isoformat(), "release_date": t.date().isoformat(), "release_berlin": t.strftime("%H:%M"), "holiday": holiday}


def cot_rhythm(status: dict | None, prev: dict | None, today: str) -> dict:
    """
    {"compact": bool, "fresh": bool, "as_of", "prev_as_of", "next_as_of", "release_date", "release_berlin", "text"}. compact = отчетът е същият като в предишния бриф (вече показан изцяло)
    и данните не са стари. Нов отчет, липсващ предишен бриф, стари данни (банерът на секцията) или пропуснат петък (отчетът е публикуван, а го няма) → цялата секция (compact False).
    Грешка → {"compact": False}.
    """
    try:
        st = status or {}
        as_of = st.get("as_of")
        if not as_of or st.get("stale"):
            return {"compact": False, "fresh": False, "as_of": as_of, "text": None}
        prev_as_of = (((prev or {}).get("cot_status")) or {}).get("as_of")
        rel = cftc_next_release(as_of)
        late = rel["release_date"] < str(today)[:10] and not rel["holiday"]        # при петък-празник отчетът е след него — не е „закъснял“
        fresh = prev_as_of != as_of
        if fresh and not late:
            text = None                                                              # първият бриф с този отчет — цялата секция, без ред
        elif late:
            text = (f"COT: отчетът, публикуван в петък {_dm(rel['release_date'])}, още не е в данните — показан е отчетът към {_dm(as_of)}")
        elif rel["holiday"]:
            text = (f"COT: без нови данни — отчет към {_dm(as_of)}; петък {_dm(rel['release_date'])} е празник в САЩ — следващият отчет е след него (по графика на CFTC)")
        else:
            text = (f"COT: без нови данни — отчет към {_dm(as_of)}, следващ отчет петък {_dm(rel['release_date'])} (публикуван {rel['release_berlin']} Берлин)")
        return {"compact": bool(not fresh and not late), "fresh": fresh, "late": late, "as_of": as_of, "prev_as_of": prev_as_of, **rel, "text": text}
    except Exception as e:
        print(f"[data_rhythm] cot_rhythm: {type(e).__name__}: {e}")
        return {"compact": False}
