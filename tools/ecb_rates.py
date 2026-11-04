"""
tools/ecb_rates.py — курсовете на ЕЦБ за данъчната страница (docs/tax.html): сваля eurofxref-hist.zip от ЕЦБ и записва docs/eurofxref-hist.csv до страницата,
за да не прави браузърът заявки навън (05.11.2026, tax-fixes). Пуска се от daily_brief.yml след брифа (continue-on-error).
Graceful degradation: при провал (мрежа, повреден архив, стар или непълен файл) старият файл остава непокътнат и скриптът завършва с код 0 и ред в лога.
Употреба: python tools/ecb_rates.py docs/eurofxref-hist.csv
"""
import csv, io, os, sys, zipfile, datetime, urllib.request

URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
MIN_ROWS = 5000                      # историята е от 1999 — ~7 000 работни дни; по-малко = непълен файл
MAX_AGE_DAYS = 10                    # най-новият курс трябва да е от последните 10 дни (празниците на TARGET са до 4 поредни дни)


def extract(data: bytes, today: datetime.date) -> str:
    """zip от ЕЦБ → текстът на eurofxref-hist.csv; ValueError, ако не е пълен и свеж файл с курсове."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"очакван един CSV в архива, има {names}")
        text = z.read(names[0]).decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    head = [h.strip() for h in rows[0]] if rows else []
    if not head or head[0] != "Date" or "USD" not in head:
        raise ValueError(f"непознато заглавие: {head[:5]}")
    dates = sorted(r[0] for r in rows[1:] if r and len(r[0]) == 10)
    if len(dates) < MIN_ROWS:
        raise ValueError(f"само {len(dates)} дни")
    newest = datetime.date.fromisoformat(dates[-1])
    if (today - newest).days > MAX_AGE_DAYS:
        raise ValueError(f"най-новият курс е от {newest}")
    usd = head.index("USD")
    last = next(r for r in rows[1:] if r and r[0] == dates[-1])
    if not float(last[usd]) > 0:
        raise ValueError("няма USD за последния ден")
    return text


def main(out_path: str) -> int:
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "market-brief tax page"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        text = extract(data, datetime.date.today())
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, out_path)
        print(f"ecb_rates: {out_path} обновен ({len(text) // 1024} KB)")
    except Exception as e:                                            # старият файл остава — страницата казва докъде стигат курсовете
        print(f"ecb_rates: НЕ е обновен ({type(e).__name__}: {e}) — остава предишният файл")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "docs/eurofxref-hist.csv"))
