"""
Предупреждения за данни в брифа (пакет 2 · т.6 и т.7). Чисти функции, без мрежа.

Идея: празен резултат, който идва от ПРОВАЛ при теглене (паднал Yahoo, спряла публикация на CFTC), не бива да изглежда като
"днес няма нищо". main.py събира тук състоянията на модулите (sector_layer.LAST_STATUS, screener.LAST_STATUS) и ги слага в
brief["data_warnings"] — [{"source", "level", "message"}]; render ги показва като банер най-горе (dashboard и имейл).
"""
from __future__ import annotations


def collect(sector_status: dict | None, screener_status: dict | None, *, rotation_count: int | None = None) -> list[dict]:
    out: list[dict] = []
    ss = sector_status or {}
    if ss and not ss.get("ok", True):
        out.append({
            "source": "sector_rotation", "level": "error",
            "message": ("Секторна ротация: Yahoo Finance не върна данни"
                        + (f" ({ss['reason']})" if ss.get("reason") else "")
                        + " — ротацията НЕ е изчислена; секторната карта, водещите сектори и маркерите SECT✓ са празни днес."),
        })
    sc = screener_status or {}
    kind = sc.get("kind") or ""
    reason = f" ({sc['reason']})" if sc.get("reason") else ""
    if kind in ("spy_failed", "no_history", "crashed"):
        out.append({
            "source": "screener", "level": "error",
            "message": ("Скрийнър: Yahoo Finance не върна ценови данни" + reason +
                        " — празният списък с кандидати (Action/Watchlist) днес е заради липса на данни, "
                        "НЕ защото няма сетъпи."),
        })
    elif kind == "universe_empty":
        out.append({
            "source": "screener", "level": "error",
            "message": "Скрийнър: списъкът с тикъри (Wikipedia) не се зареди" + reason +
                       " — днес няма скрининг, празните Action/Watchlist не значат 'няма сетъпи'.",
        })
    elif kind == "partial" and sc.get("batches_failed"):
        out.append({
            "source": "screener", "level": "warn",
            "message": (f"Скрийнър: {sc['batches_failed']} от {sc.get('batches')} партиди тикъри не се изтеглиха от Yahoo — "
                        f"скринингът е върху {sc.get('with_history')} от {sc.get('universe')} тикъра; RS rating перцентилът "
                        f"и списъкът с кандидати са непълни."),
        })
    return out
