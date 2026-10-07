#!/usr/bin/env python3
"""
Диагностика на 13F (само четене, нищо не пише): за всеки мениджър от config.DATAROMA_CIK показва какво вижда SEC EDGAR — последните 13F-подавания (форма, дата, период, документ),
дали има ново подаване след края на последното просрочено тримесечие и как кодът чете двата последни филинга (редове, покритие на акциите, сума, мащаб и основанието му).

Нужен е EDGAR_UA — декларираният от теб User-Agent за SEC ("Име имейл"); стойността се чете от средата и НИКОГАЗ не се печата. SEC връща 403 на анонимен User-Agent.
Пускане (от корена на репото):
    EDGAR_UA="Име Фамилия имейл@пример.com" .venv/bin/python tools/probe_13f.py              # всички мениджъри
    EDGAR_UA="…" .venv/bin/python tools/probe_13f.py pershing                                  # само мениджъри, чието име съдържа низа
    EDGAR_UA="…" .venv/bin/python tools/probe_13f.py pershing --forms                          # + всички форми на CIK-а за последните 200 дни (напр. дали Q2 е подаден като 13F-HR/A, 13F-NT или от друг филър)
Не е тест: run_tests.py гледа само test_*.py, а тестовете нямат достъп до мрежата.
"""
import os
import sys
import time
import datetime as dt
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import requests
import config
from src import dataroma


def main(argv: list[str]) -> int:
    ua = os.getenv("EDGAR_UA", "").strip()
    if not ua:
        print("Липсва EDGAR_UA в средата (виж горния коментар). Нищо не е изтеглено.")
        return 2
    headers = {"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}
    dataroma._EDGAR_UA = headers                                    # същият заглавен ред ползва и кодът на проекта (_info_table / _recent_13f_filings)
    show_forms = "--forms" in argv
    needles = [a.lower() for a in argv if not a.startswith("--")]
    today = dt.date.today()
    q_end, deadline = dataroma.last_quarter_deadline(today)
    print(f"Днес {today}; последното просрочено тримесечие: {q_end} (срок {deadline}) — мениджър без 13F след {q_end} закъснява.\n")
    for cik, name in config.DATAROMA_CIK.items():
        if needles and not any(n in name.lower() for n in needles):
            continue
        print(f"═══ {name} · CIK {cik}")
        try:
            r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=headers, timeout=20)
            r.raise_for_status()
            sub = r.json()
        except Exception as e:
            print(f"   submissions: {type(e).__name__}: {e}\n")
            continue
        print(f"   име в SEC: {sub.get('name')} · филър {sub.get('entityType') or '?'}")
        rec = (sub.get("filings") or {}).get("recent") or {}
        rows = list(zip(rec.get("form", []), rec.get("filingDate", []), rec.get("reportDate", []), rec.get("accessionNumber", []), rec.get("primaryDocument", [])))
        f13 = [x for x in rows if str(x[0]).upper().startswith("13F")]
        for form, fdate, rdate, acc, doc in f13[:6]:
            print(f"   {form:<9} подадено {fdate} за период {rdate or '?'}  {acc}  {doc}")
        hr = sorted((x for x in f13 if x[0] == "13F-HR"), key=lambda x: x[1], reverse=True)
        if hr:
            late = dataroma.late_filer(hr[0][1], today)
            print(f"   → последен 13F-HR: {hr[0][1]} — {'ЗАКЪСНЯВА (няма подаване след ' + str(q_end) + ')' if late else 'в срок'}")
            if late:
                other = [x for x in f13 if x[1] > str(q_end) and x[0] != "13F-HR"]
                print(f"     други 13F форми след {q_end}: {other or 'няма'}  (13F-HR/A и 13F-NT не се броят от кода — _recent_13f_filings взима само 13F-HR)")
        else:
            print("   → няма 13F-HR в последните подавания (recent[] е ограничен до ~1000 записа)")
        if show_forms:
            since = str(today - dt.timedelta(days=200))
            print(f"   всички форми от {since}: " + ", ".join(f"{x[0]} {x[1]}" for x in rows if x[1] >= since)[:1500])
        for label, (form, fdate, rdate, acc, doc) in zip(("текущ", "предишен"), hr[:2]):
            time.sleep(0.25)                                         # SEC: до 10 заявки в секунда
            tbl = dataroma._info_table(cik, acc)
            agg = dataroma._aggregate_by_cusip(tbl)
            scale, basis = dataroma._value_scale(agg, fdate)
            total = sum(a["value"] for a in agg.values()) * scale
            cov = dataroma.shares_coverage(agg)
            top = sorted(agg.values(), key=lambda a: a["value"], reverse=True)[:3]
            print(f"   {label}: {len(tbl)} реда → {len(agg)} CUSIP · покритие на акциите {('—' if cov is None else f'{cov:.0%}')} · сума ${total:,.0f} · мащаб ×{scale} ({basis})"
                  + "".join(f"\n       {a['issuer'][:28]:<28} стойност {a['value']:>16,.0f}  акции {a['shares']:>14,.0f}" for a in top))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
