"""
Предупреждения за данни в брифа (пакет 2 · т.6 и т.7). Чисти функции, без мрежа.

Идея: празен резултат, който идва от ПРОВАЛ при теглене (паднал Yahoo, спряла публикация на CFTC), не бива да изглежда като
"днес няма нищо". main.py събира тук състоянията на модулите (sector_layer.LAST_STATUS, screener.LAST_STATUS) и ги слага в
brief["data_warnings"] — [{"source", "level", "message"}]; render ги показва като банер най-горе (dashboard и имейл).
"""
from __future__ import annotations


def _cot_warning(cot_diag: dict | None) -> list[dict]:
    """COT: пазари, за които моделът не върна теза нито след повторното извикване (виж ai_brief.cot_theses) — без ред в диагностиката те бяха мълчалива загуба (06.10: 4 от 20)."""
    nr = (cot_diag or {}).get("not_returned") or []
    if not nr:
        return []
    total = (cot_diag or {}).get("extremes")
    return [{"source": "cot", "level": "warn",
             "message": (f"COT: моделът не върна теза за {len(nr)}{f' от {total}' if total else ''} пазара ({', '.join(nr)}) и след повторно извикване — "
                         f"показват се с директната теза от таблицата (или със стара теза, ако има); следващият run опитва пак.")}]


def _marker_warnings(insider_status: dict | None, uov_diag: dict | None) -> list[dict]:
    """
    Пакет 4б т.б/т.в: секциите "Insider Buying" и "Unusual Options" отпаднаха — остават маркерите INS✓/UOV✓. Липсващ маркер, защото тегленето/снимката
    са паднали, не бива да изглежда като "няма покупки / нормален обем": тук е банерът за провала (легитимната нула не е предупреждение).
    """
    out: list[dict] = []
    ins = insider_status or {}
    if ins.get("kind") == "failed" and not ins.get("stale"):
        out.append({"source": "insider", "level": "warn",
                    "message": f"Insider buying: {ins.get('note')} — маркерите INS✓ липсват днес; това НЕ значи, че няма insider покупки."})
    elif ins.get("kind") == "failed":
        out.append({"source": "insider", "level": "warn",
                    "message": (f"Insider buying: днешното теглене не успя ({ins.get('note')}) — маркерите INS✓ са от тегленето на "
                                f"{ins.get('data_date') or 'неизвестна дата'}.")})
    elif ins.get("kind") == "ok_partial":
        out.append({"source": "insider", "level": "warn", "message": f"Insider buying: {ins.get('note')}."})
    u = uov_diag or {}
    if u.get("requested") and not u.get("with_ratio"):
        reasons = list((u.get("missing") or {}).values())
        why = u.get("snapshot_missing_reason") or (max(set(reasons), key=reasons.count) if reasons else "няма данни")
        out.append({"source": "unusual_options", "level": "warn",
                    "message": f"Unusual options: за нито един кандидат няма съотношение обем/OI ({why}) — маркерите UOV✓ липсват днес; това НЕ значи нормален обем."})
    return out


def _qm_warning(qm_diag: dict | None) -> list[dict]:
    """Qullamaggie скенерът: празен списък от провал на данните не бива да се чете като "днес няма сетъпи" (графика на скрийнъра)."""
    d = qm_diag
    if not d:
        return []
    if d.get("ok") is False:
        return [{"source": "qm_breakout", "level": "warn",
                 "message": (f"Qullamaggie скенер: не се изпълни ({d.get('error') or 'Yahoo не върна данни'}) — празният списък НЕ значи, че няма кандидати за пробив днес.")}]
    if d.get("batches_failed"):
        return [{"source": "qm_breakout", "level": "warn",
                 "message": (f"Qullamaggie скенер: {d['batches_failed']} от {d.get('batches')} партиди тикъри не се изтеглиха — списъкът е върху {d.get('with_history')} от "
                             f"{d.get('universe')} тикъра и може да е непълен.")}]
    return []


def _ep_warning(ep: dict | None) -> list[dict]:
    """EP наблюдението: провал на after-hours теглене не бива да се чете като "няма гапове днес"."""
    if not ep or ep.get("ok") is not False and not (ep.get("diag") or {}).get("batches_failed"):
        return []
    d = ep.get("diag") or {}
    if ep.get("ok") is False:
        why = (ep.get("notes") or ["Yahoo не върна after-hours данни"])[0]
        return [{"source": "qm_ep", "level": "warn",
                 "message": f"EP наблюдение (after-hours): не се изпълни ({why}) — празният списък НЕ значи, че няма гапове след затваряне."}]
    return [{"source": "qm_ep", "level": "warn",
             "message": (f"EP наблюдение (after-hours): {d['batches_failed']} от {d.get('batches')} партиди тикъри не се изтеглиха — списъкът с гапове може да е непълен.")}]


def collect(sector_status: dict | None, screener_status: dict | None, *, rotation_count: int | None = None,
            cot_diag: dict | None = None, insider_status: dict | None = None, uov_diag: dict | None = None,
            qm_diag: dict | None = None, qm_ep: dict | None = None) -> list[dict]:
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
    out += _cot_warning(cot_diag)
    out.extend(_marker_warnings(insider_status, uov_diag))
    out.extend(_qm_warning(qm_diag))
    out.extend(_ep_warning(qm_ep))
    return out
