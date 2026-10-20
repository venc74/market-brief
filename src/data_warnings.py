"""
Предупреждения за данни в брифа (пакет 2 · т.6 и т.7). Чисти функции, без мрежа.

Идея: празен резултат, който идва от ПРОВАЛ при теглене (паднал Yahoo, спряла публикация на CFTC), не бива да изглежда като
"днес няма нищо". main.py събира тук състоянията на модулите (sector_layer.LAST_STATUS, screener.LAST_STATUS) и ги слага в
brief["data_warnings"] — [{"source", "level", "message"}]; render ги показва като банер най-горе (dashboard и имейл).
"""
from __future__ import annotations

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config


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
    elif u.get("with_ratio") and "basket" in u and (u.get("basket") or {}).get("p") is None \
            and not any((d or {}).get("mode") == "history" for d in (u.get("decisions") or {}).values()):
        # 08.10.2026: съотношения има, но няма референтна кошница за деня (и няма собствена история) → маркер само при абсолютния праг
        out.append({"source": "unusual_options", "level": "warn",
                    "message": (f"Unusual options: няма референтна кошница за деня ({(u.get('basket') or {}).get('reason') or 'липсва'}) — UOV✓ се слага само при "
                                f"съотношение ≥ {u.get('min_ratio')}×; липсата на маркер НЕ значи нормален обем.")})
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


def _glb_warning(status: dict | None) -> list[dict]:
    """
    С3 (втори преглед, 10.10.2026): GLB скрийнърът — провал не бива да изглежда като "няма кандидати", а книгата "GLB по Уиш" губи деня (сигналите са
    "свеж пробив на последния цял бар" — утре вече не са свежи). До 10.10 секцията просто изчезваше. Легитимна нула (изпълнен, 0 кандидати) не е предупреждение.
    """
    st = status or {}
    if not st:
        return []
    if st.get("ok") is False:
        return [{"source": "glb", "level": "warn",
                 "message": (f"GLB скрийнър: не се изпълни ({st.get('error') or 'Yahoo не върна данни'}) — празният списък НЕ значи, че няма GLB кандидати; "
                             "книгата „GLB по Уиш“ не получи сигнали за днешния бар (той не се записва по-късно).")}]
    if st.get("batches_failed"):
        return [{"source": "glb", "level": "warn",
                 "message": (f"GLB скрийнър: {st['batches_failed']} от {st.get('batches')} партиди тикъри не се изтеглиха — списъкът (и сигналите за книгата "
                             f"„GLB по Уиш“) е върху {st.get('with_history')} от {st.get('universe')} тикъра и може да е непълен.")}]
    return []


def _canary_warning(c: dict | None) -> list[dict]:
    """С5 (10.10.2026): split корекцията на Yahoo — close-ът на NVDA за 07.06.2024 не е ≈ $120.888 → нивата и реплеите може да са изкривени."""
    if not c or c.get("ok") is not False:
        return []
    return [{"source": "data_canary", "level": "error",
             "message": (f"Данни: split корекцията на Yahoo изглежда грешна — close на {c.get('ticker')} за {c.get('date')} е ${c.get('close')} "
                         f"вместо ≈ ${c.get('expected')} (сплит 10:1 на 10.06.2024). Ценовите нива (pivot, стопове, GLB линии) и книгите може да са изкривени днес.")}]


def _corp_warning(diag: dict | None) -> list[dict]:
    """Проверката за корпоративни действия (маркерът ⚠ върху картите): паднала проверка не бива да се чете като "няма събития"."""
    if not diag or diag.get("ok", True):
        return []
    return [{"source": "corp_actions", "level": "warn",
             "message": (f"Корпоративни действия: проверката не се изпълни ({diag.get('error') or 'Yahoo не върна данни'}) — днес НИЩО не е изключено заради отделяне или сплит с нецял коефициент; "
                         f"тикър с такова събитие може да е на картите с приблизителна история.")}]                   # 13.10.2026: изключване вместо маркер


def _ai_lost_warning(lost: list | None) -> list[dict]:
    """16.10.2026 (В7): тикъри без AI наратив днес (паднал batch / пропуснати от модела) — класификацията им е от кода."""
    if not lost:
        return []
    return [{"source": "ai", "level": "warn",
             "message": (f"AI наративи: моделът не върна текст за {len(lost)} тикъра ({', '.join(lost)}) — класификацията им е от кода (потвърден пробив → Action, "
                         "останалите → Watchlist), картите са без AI текст днес.")}]


def _dd_warning(status: dict | None) -> list[dict]:
    """16.10.2026 (В8, трети преглед): distribution days — failed (нито SPY, нито QQQ) / partial (единият липсва). Липсата НЕ е нечервен ден за блока на Offensive."""
    st = status or {}
    if not st or st.get("status") in (None, "ok"):
        return []
    if st["status"] == "failed":
        return [{"source": "distribution_days", "level": "warn",
                 "message": "Distribution days: нито SPY, нито QQQ не се изтеглиха днес — броят и блокът на Offensive не са проверени (липсата не е нечервен ден)."}]
    miss = (st.get("missing") or ["?"])[0]
    other = "QQQ" if miss == "SPY" else "SPY"
    return [{"source": "distribution_days", "level": "warn",
             "message": f"Distribution days: {miss} не се изтегли днес — броят и блокът на Offensive са само по {other}."}]


def _spinoff_warning(diag: dict | None) -> list[dict]:
    """
    13.10.2026: предупреждението за ПРЕДСТОЯЩО отделяне (EDGAR 8-K, spinoff_watch). Паднала проверка или непроверени тикъри (бюджет / грешки) не бива да се четат като
    "няма предстоящо отделяне". Успешна проверка без засичане не е предупреждение.
    """
    d = diag or {}
    if not d:
        return []
    if not d.get("ok", True):
        return [{"source": "spinoff", "level": "warn",
                 "message": (f"Предстоящо отделяне (EDGAR 8-K): проверката не се изпълни ({d.get('error') or 'EDGAR не отговори'}) — "
                             "липсата на предупреждение днес НЕ значи, че няма предстоящо отделяне.")}]
    miss = list(d.get("unchecked") or []) + sorted({e["ticker"] for e in d.get("errors") or [] if e.get("ticker")} - set(d.get("unchecked") or []))
    if miss:
        return [{"source": "spinoff", "level": "warn",
                 "message": (f"Предстоящо отделяне (EDGAR 8-K): {len(miss)} от {d.get('requested') or '?'} тикъра не са проверени днес ({', '.join(miss[:8])}"
                             + (" …" if len(miss) > 8 else "") + ") — за тях липсата на предупреждение НЕ значи, че няма предстоящо отделяне.")}]
    return []


def _13f_warnings(status: dict | None) -> list[dict]:
    """
    13F пакет (07.10): мениджъри с покритие на акциите под прага — "нова/увеличена" не се показва за тях (не значи "няма покупки").
    Давността (закъснял 13F) НЕ е банер в "Проблем с данните днес" (08.10): етикетът "закъснява" остава само до периода в секцията на 13F
    (Pershing се оказа не закъснял, а с 13F-NT към родителя — виж dataroma._nt_successor). Легитимна нула не е предупреждение.
    """
    st = status or {}
    out = []
    lc = st.get("low_coverage") or []
    if lc:
        out.append({"source": "13f", "level": "warn",
                    "message": ("13F: броят акции не е прочетен надеждно за " + ", ".join(x["manager"] for x in lc)
                                + " — „нова/увеличена позиция“ не се показва за тях днес; това НЕ значи, че няма покупки.")})
    # 19.10.2026 (етап 2, т. 3): тикърите по CUSIP (OpenFIGI) — грешка или недовършени (бюджет) → видимо, не тиха липса на тикъри
    ct = st.get("cusip_tickers") or {}
    if ct.get("error") or ct.get("skipped"):
        why = f"OpenFIGI не отговори ({ct['error']})" if ct.get("error") else f"{ct['skipped']} CUSIP-а не стигнаха бюджета на run-а"
        out.append({"source": "13f", "level": "warn",
                    "message": (f"13F: тикърите по CUSIP не са пълни днес — {why}; {ct.get('no_ticker', 0)} от {ct.get('rows', 0)} реда са „без тикър“, "
                                f"{ct.get('by_name', 0)} — по името на емитента (може да е грешно: SPY, подаден като STATE STREET CORP).")})
    # трети преглед (16.10): мениджър без поредното предходно тримесечие — причината по мениджър ("няма 13F за …" ≠ "13F за … не се изтегли днес")
    nc = st.get("no_comparison") or []
    if nc:
        out.append({"source": "13f", "level": "warn",
                    "message": ("13F: без сравнение с предходното тримесечие — " + "; ".join(f"{x['manager']}: {x['text']}" for x in nc)
                                + ". За тях „нова/увеличена позиция“, SI✓ и големите изходи не се показват днес — това НЕ значи, че няма покупки.")})
    return out


def _partial_warnings(sector_status: dict | None, screener_status: dict | None, superinvestor_status: dict | None, glb_status: dict | None,
                      uov_diag: dict | None, ins_pos_status: dict | None, news_status: dict | None, canary: dict | None, fred_key_missing: bool) -> list[dict]:
    """
    19.10.2026 (трети преглед, т. 12): ТИХИТЕ частични провали — всеки е видим ред, не тиха липса. Пълните провали вече имаха банер; тук е "част от данните липсва".
    Измерено в 89 брифа: секторите винаги 17 от 17, 13F — 15 от 15, GLB — 903 от 903, канарчето — проверено, новините — никога празни, OI снимката — 0 неуспешни тикъра;
    пътищата в кода бяха тихи. Скрийнърът не пазеше броя тикъри с история → праг 90% от универса (голям спад; нормата се записва от днес — screener_status в брифа).
    """
    out: list[dict] = []
    ss = sector_status or {}
    if ss.get("ok") and ss.get("etfs_total") and (ss.get("etfs_ok") or 0) < ss["etfs_total"]:
        out.append({"source": "sector_rotation", "level": "warn",
                    "message": (f"Секторна ротация: {ss.get('etfs_ok')} от {ss['etfs_total']} секторни ETF-а — без данни днес: {', '.join(ss.get('missing') or []) or '?'}; "
                                "картата и водещите сектори са без тях.")})
    sc = screener_status or {}
    # 20.10.2026 (етап 3б): прагът е спрямо нормалния фон — тикъри БЕЗ НИТО ЕДИН бар ≥ config.PARTIAL_DATA_WARN_SHARE от универса (фон 0 от 903; пробното пускане при
    # ограничение — 34 при 865 от 903 с история, а старият праг "с история < 90%" не сработи). Късата история (нови листинги) не се брои.
    nb = sc.get("no_bars_n")
    if sc.get("kind") in ("ok", "partial") and sc.get("universe") and not sc.get("batches_failed") and nb is not None \
            and nb >= config.PARTIAL_DATA_WARN_SHARE * sc["universe"]:
        names = ", ".join((sc.get("no_bars") or [])[:8]) + (" …" if nb > 8 else "")
        out.append({"source": "screener", "level": "warn",
                    "message": (f"Скрийнър: за {nb} от {sc['universe']} тикъра Yahoo не върна нито един бар днес ({names}) — без грешка в партидата; нормално е 0. "
                                f"Скринингът е върху {sc.get('with_history')} тикъра — RS rating перцентилът и кандидатите може да са непълни; липсващите НЕ са оценени.")})
    fu = sc.get("fundamentals_unavailable") or []
    if fu:                                                       # 20.10.2026 (етап 3б): LLY в пробното пускане — таймаут на .info, отпадна с общия текст и без банер
        out.append({"source": "screener", "level": "warn",
                    "message": (f"CANSLIM: фундаментите (Yahoo .info) на {len(fu)} от {sc.get('fundamentals_checked') or '?'} проверени кандидата не се изтеглиха днес "
                                f"({', '.join(fu[:8])}{' …' if len(fu) > 8 else ''}) — те НЕ са оценени и липсват в Action/Watchlist; това не значи, че не минават CANSLIM.")})
    si = superinvestor_status or {}
    if si.get("kind") in ("ok", "legit_zero") and si.get("managers_total") and (si.get("managers_with_data") or 0) < si["managers_total"]:
        out.append({"source": "13f", "level": "warn",
                    "message": (f"13F: {si.get('managers_with_data')} от {si['managers_total']} мениджъра с данни днес — за останалите ходовете, SI✓ и изходите липсват; "
                                "това НЕ значи, че нямат промени.")})
    g = glb_status or {}
    if g.get("ok") and g.get("universe") and not g.get("batches_failed") and (g.get("with_history") or 0) < 0.99 * g["universe"]:
        out.append({"source": "glb", "level": "warn",
                    "message": (f"GLB скрийнър: {g['universe'] - (g.get('with_history') or 0)} от {g['universe']} тикъра без история днес (Yahoo не върна данни без грешка) — "
                                "списъкът и сигналите за книгата „GLB по Уиш“ може да са непълни.")})
    u = uov_diag or {}
    if u.get("snapshot_failed"):
        f = u["snapshot_failed"]
        out.append({"source": "unusual_options", "level": "warn",
                    "message": (f"Unusual options: следобедната OI снимка за {u.get('snapshot_session') or '?'} не взе {len(f)} тикъра ({', '.join(map(str, f[:8]))}"
                                + (" …" if len(f) > 8 else "") + ") — за тях UOV✓ липсва, това НЕ значи нормален обем.")})
    ip = ins_pos_status or {}
    if ip.get("kind") in ("failed", "ok_partial"):
        out.append({"source": "insider", "level": "warn",
                    "message": f"Insider buying (позициите в книгите): {ip.get('note')} — INS✓ върху позициите може да липсва; това НЕ значи, че няма insider покупки."})
    ns = news_status or {}
    if ns and not ns.get("ok"):
        out.append({"source": "news", "level": "warn",
                    "message": (f"Значими новини: няма днес ({ns.get('reason') or 'неизвестна причина'}) — макро текстът, тезите и проверката на AI текста на картите са без "
                                "новинарски фон; това НЕ значи, че няма новини.")})
    c = canary or {}
    if c and c.get("ok") is None:
        out.append({"source": "data_canary", "level": "warn",
                    "message": f"Данни: канарчето за split корекцията на Yahoo не провери днес ({c.get('error') or 'няма данни'}) — корекцията не е сверена."})
    if fred_key_missing:
        out.append({"source": "fred", "level": "warn",
                    "message": "FRED: липсва FRED_API_KEY — серийте от FRED (2s10s, Net Liquidity, SOFR − IORB, ядрената инфлация) са празни днес; скритите индикатори не са „без данни на пазара“."})
    return out


def collect(sector_status: dict | None, screener_status: dict | None, *, rotation_count: int | None = None,
            cot_diag: dict | None = None, insider_status: dict | None = None, uov_diag: dict | None = None,
            qm_diag: dict | None = None, qm_ep: dict | None = None, superinvestor_status: dict | None = None, corp_diag: dict | None = None,
            glb_status: dict | None = None, canary: dict | None = None, health: list | None = None, spinoff_diag: dict | None = None,
            dd_status: dict | None = None, ai_lost: list | None = None, ins_pos_status: dict | None = None, news_status: dict | None = None,
            fred_key_missing: bool = False) -> list[dict]:
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
    markers = _marker_warnings(insider_status, uov_diag)
    if any(h.get("check") == "oi_snapshot" for h in health or []) and (uov_diag or {}).get("snapshot_missing_reason"):
        # 12.10.2026: един банер за липсващата OI снимка — здравната проверка (последната снимка, кой job да се провери); UOV банерът за СЪЩАТА причина
        # отпада (на 12.10 двата казваха едно и също). UOV банер по друга причина (снимката е налице, съотношения няма) остава.
        markers = [w for w in markers if w.get("source") != "unusual_options"]
    out.extend(markers)
    out.extend(_qm_warning(qm_diag))
    out.extend(_ep_warning(qm_ep))
    out.extend(_13f_warnings(superinvestor_status))
    out.extend(_corp_warning(corp_diag))
    out.extend(_spinoff_warning(spinoff_diag))
    out.extend(_dd_warning(dd_status))
    out.extend(_ai_lost_warning(ai_lost))
    out.extend(_glb_warning(glb_status))
    out.extend(_canary_warning(canary))
    out.extend(_partial_warnings(sector_status, screener_status, superinvestor_status, glb_status, uov_diag, ins_pos_status, news_status, canary, fred_key_missing))
    for h in health or []:              # здравен монитор (10.10): очаквани артефакти, които липсват (src/health_monitor.py)
        out.append({"source": f"health:{h.get('check')}", "level": "warn", "message": "Здравна проверка: " + h.get("message", "")})
    return out
