"""
21.10.2026 (етап 4, „ритъм на данните“): източниците с редки отчети се показват изцяло само в първия бриф след нов отчет, а в другите дни — с един ред кога е следващият.
  • COT (CFTC, седмичен): данни към вторника, публикувани в петък в 15:30 ET (21:30 Берлин; 20:30 в седмиците, в които САЩ и ЕС още не са сменили часа заедно).
  • 13F (SEC, тримесечен): цялата секция само при нов 13F на някой от мениджърите спрямо предишния бриф; иначе ред с датата на последния и следващата вълна
    (срокът — 45 дни след края на тримесечието, преместен през почивни дни и празници: dataroma.filing_deadline).
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


_WD = ("понеделник", "вторник", "сряда", "четвъртък", "петък", "събота", "неделя")


def release_as_of(release: dt.date) -> dt.date:
    """16.11.2026 (т. 7): данните на отчет, публикуван на `release` — последният вторник ПРЕДИ него (петък → 3 дни назад; изместен в понеделник → 6 дни назад). Чиста функция."""
    return release - dt.timedelta(days=((release.weekday() - 1) % 7) or 7)


def cftc_next_release(as_of: str) -> dict:
    """
    Следващият седмичен отчет след отчета към as_of: данни към деня 7 дни по-късно → датата на публикуване и часът в Берлин (15:30 ET).
    16.11.2026 (пакет 16.11, т. 7): по официалния график на CFTC (config.CFTC_COT_RELEASES) — и изместените заради празник (понеделник 16.11, 30.11, 28.12); извън графика —
    петъкът след данните (както до 16.11), "source": "rule".
    """
    d = dt.date.fromisoformat(as_of) + dt.timedelta(days=7)
    hit = next((r for r in sorted(dt.date.fromisoformat(x) for x in config.CFTC_COT_RELEASES) if release_as_of(r) == d), None)
    rel = hit or d + dt.timedelta(days=(4 - d.weekday()) % 7)
    t = dt.datetime(rel.year, rel.month, rel.day, 15, 30, tzinfo=_NY).astimezone(_BERLIN)
    holiday = hit is None and rel.isoformat() in config.NYSE_HOLIDAYS                 # извън графика: петък-празник — CFTC мести отчета
    return {"next_as_of": d.isoformat(), "release_date": t.date().isoformat(), "release_berlin": t.strftime("%H:%M"), "holiday": holiday,
            "weekday": _WD[rel.weekday()], "delayed": bool(hit and hit.weekday() != 4), "source": "schedule" if hit else "rule"}


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
            text = (f"COT: отчетът, публикуван в {rel['weekday']} {_dm(rel['release_date'])}, още не е в данните — показан е отчетът към {_dm(as_of)}")
        elif rel["holiday"]:
            text = (f"COT: без нови данни — отчет към {_dm(as_of)}; петък {_dm(rel['release_date'])} е празник в САЩ — следващият отчет е след него (по графика на CFTC)")
        else:                                                                        # 16.11.2026 (т. 7): денят — по графика на CFTC
            text = (f"COT: без нови данни — отчет към {_dm(as_of)}, следващ отчет {rel['weekday']} {_dm(rel['release_date'])}"
                    + (" — изместен заради празник, по графика на CFTC" if rel.get("delayed") else "") + f" (публикуван {rel['release_berlin']} Берлин)")
        return {"compact": bool(not fresh and not late), "fresh": fresh, "late": late, "as_of": as_of, "prev_as_of": prev_as_of, **rel, "text": text}
    except Exception as e:
        print(f"[data_rhythm] cot_rhythm: {type(e).__name__}: {e}")
        return {"compact": False}


def next_13f_wave(today: str) -> str:
    """Срокът за 13F на най-ранното тримесечие, чийто срок е днес или по-късно (dataroma.filing_deadline: край + 45 дни, през почивни дни и празници)."""
    from src import dataroma
    d = dt.date.fromisoformat(str(today)[:10])
    ends = [dt.date(y, m, last) for y in (d.year - 1, d.year, d.year + 1) for m, last in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return min(dataroma.filing_deadline(q) for q in ends if dataroma.filing_deadline(q) >= d).isoformat()


def _quarter_end_for_wave(wave: str) -> str:
    """Краят на тримесечието, чийто срок е `wave` (срокът е 45 дни след края, преместен напред през почивни дни) — последният край ≤ wave − 45 дни."""
    d = dt.date.fromisoformat(wave) - dt.timedelta(days=45)
    ends = [dt.date(y, m, last) for y in (d.year - 1, d.year) for m, last in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return max(e for e in ends if e <= d).isoformat()


def thirteenf_rhythm(status: dict | None, prev: dict | None, today: str) -> dict:
    """
    {"compact", "fresh", "new", "latest", "next_wave", "text"}. compact = нито един мениджър няма по-нов 13F от предишния бриф (status["filings"] срещу неговия). Нов 13F, липсващ предишен бриф
    или поле (брифове отпреди 21.10), провалено теглене (kind извън ok / legit_zero) → цялата секция (compact False). Грешка → {"compact": False}.
    """
    try:
        st = status or {}
        filings = st.get("filings")
        prevf = (((prev or {}).get("superinvestor_status")) or {}).get("filings")
        if not filings or st.get("kind") not in ("ok", "legit_zero") or prevf is None:
            return {"compact": False, "fresh": False, "text": None}
        new = sorted(m for m, d in filings.items() if d and d > (prevf.get(m) or ""))
        latest = max(d for d in filings.values() if d)
        wave = next_13f_wave(today)
        # 16.11.2026 (пакет 16.11, т. 11): и в деня с ново подаване — кой е подал и срокът; до 16.11 редът изчезваше точно в деня на срока (Baupost и Pabrai — 13.11, срокът — 16.11)
        q_end = _quarter_end_for_wave(wave)
        filed_q = sum(1 for d in filings.values() if d and d > q_end)
        if new:
            text = (f"13F: нови подавания — {', '.join(f'{m} ({_dm(filings[m])})' for m in new)}; срокът за тримесечието до {_dm(q_end)} — {_dm(wave)} "
                    f"(45 дни след края му), подали са {filed_q} от {len(filings)}")
        else:
            text = f"13F: последни 13F от {_dm(latest)} — следваща вълна около {_dm(wave)} (срокът е 45 дни след края на тримесечието)"
        return {"compact": not new, "fresh": bool(new), "new": new, "latest": latest, "next_wave": wave, "text": text, "filed_for_quarter": filed_q}
    except Exception as e:
        print(f"[data_rhythm] thirteenf_rhythm: {type(e).__name__}: {e}")
        return {"compact": False}
