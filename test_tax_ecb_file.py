"""
05.11.2026 (tax-fixes): tools/ecb_rates.py — курсовете на ЕЦБ до данъчната страница (docs/eurofxref-hist.csv; daily_brief.yml го опреснява след брифа).
СИНТЕТИЧЕН архив (не реалният eurofxref-hist.zip — средата за разработка не стига ecb.europa.eu); без мрежа, без запис в docs/.
Проверява: пълен и свеж файл → текстът; стар (над 10 дни), кратък, без USD, два CSV в архива → отказ (старият файл остава); main() при провал → код 0, файлът непокътнат.
"""
import io, sys, zipfile, datetime, pathlib, tempfile
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT / "tools"))
import ecb_rates

TODAY = datetime.date(2026, 11, 5)
def make(days=6000, newest=datetime.date(2026, 11, 4), head="Date,USD,JPY,", files=1):
    rows = [head] + [f"{newest - datetime.timedelta(days=i)},1.1{i % 10},150.0," for i in range(days)]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k in range(files):
            z.writestr(f"eurofxref-hist{k or ''}.csv", "\n".join(rows) + "\n")
    return b.getvalue()

print("── 1. пълен и свеж файл ──")
t = ecb_rates.extract(make(), TODAY)
assert t.startswith("Date,USD,JPY,") and t.count("\n") == 6001
print("  ✓ 6000 дни до 04.11.2026 → приет")

print("── 2. отказ ──")
for name, data in [("стар", make(newest=datetime.date(2026, 10, 20))), ("кратък", make(days=100)), ("без USD", make(head="Date,JPY,GBP,")), ("два CSV", make(files=2))]:
    try:
        ecb_rates.extract(data, TODAY); raise AssertionError(name + " — приет")
    except ValueError as e:
        print(f"  ✓ {name}: {e}")

print("── 3а. симулиран провал / таймаут / повреден отговор / неуспешен запис — код 0, ::warning::, старият файл остава ──")
import contextlib, socket, urllib.error

class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

def run_with(fake, prepare=None):
    with tempfile.TemporaryDirectory() as d:
        out = pathlib.Path(d) / "eurofxref-hist.csv"; out.write_text("стар файл", encoding="utf-8")
        if prepare: prepare(out)
        orig = ecb_rates.urllib.request.urlopen
        ecb_rates.urllib.request.urlopen = fake
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = ecb_rates.main(str(out))
        finally:
            ecb_rates.urllib.request.urlopen = orig
        return code, out.read_text(encoding="utf-8") if out.is_file() else None, buf.getvalue(), sorted(x.name for x in pathlib.Path(d).iterdir())

def boom(exc):
    def f(*a, **k): raise exc
    return f
for name, fake in [("таймаут", boom(socket.timeout("timed out"))), ("TimeoutError", boom(TimeoutError())), ("мрежа", boom(urllib.error.URLError("no route"))),
                   ("HTTP 503", boom(urllib.error.HTTPError(ecb_rates.URL, 503, "unavailable", {}, None))), ("не е zip", lambda *a, **k: Resp(b"<html>maintenance</html>")),
                   ("стар файл в архива", lambda *a, **k: Resp(make(newest=datetime.date.today() - datetime.timedelta(days=40))))]:
    code, text, log, names = run_with(fake)
    assert code == 0 and text == "стар файл" and "::warning title=ECB rates::" in log and names == ["eurofxref-hist.csv"], (name, code, text, log, names)
    print(f"  ✓ {name}: код 0, ::warning::, старият файл остава")
def no_write(out):                                                   # записът пада: на мястото на .tmp — папка
    (out.parent / "eurofxref-hist.csv.tmp").mkdir()
code, text, log, names = run_with(lambda *a, **k: Resp(make(newest=datetime.date.today())), no_write)
assert code == 0 and text == "стар файл" and "::warning" in log, (code, text, log)
print("  ✓ неуспешен запис: код 0, ::warning::, старият файл остава")
code, text, log, names = run_with(lambda *a, **k: Resp(make(newest=datetime.date.today())))
assert code == 0 and text.startswith("Date,USD,JPY,") and "обновен" in log and names == ["eurofxref-hist.csv"], (code, log, names)
print("  ✓ успех (синтетичен архив): файлът е заменен, без .tmp")

print("── 3. стъпката в daily_brief.yml ──")                                     # main() — само със симулиран urlopen (3а): тестът не прави мрежова заявка
yml = (ROOT / ".github" / "workflows" / "daily_brief.yml").read_text(encoding="utf-8")
i = yml.index("python tools/ecb_rates.py docs/eurofxref-hist.csv")
step = yml[yml.index("- name: ECB rates for the tax page"):yml.index("- name: Commit dashboard + data")]
assert "continue-on-error: true" in step and "timeout-minutes: 3" in step and '|| echo "::warning' in step and "if:" not in step, step
assert yml.index("- name: Run the brief") < i < yml.index("git add docs/ data/")                 # след брифа, преди commit-а (който качва и docs/eurofxref-hist.csv)
commit = yml[yml.index("- name: Commit dashboard + data"):]
assert "if:" not in commit.split("run:")[0], commit[:200]                                         # commit стъпката не зависи от успеха на курсовете
import os, subprocess, stat                                                            # самият ред от workflow-а с „python“, който пада (код 3) → стъпката пак е 0
line = [l for l in step.splitlines() if l.strip().startswith("run:")][0].split("run:", 1)[1].strip()
with tempfile.TemporaryDirectory() as d:
    fake = pathlib.Path(d) / "python"; fake.write_text("#!/bin/sh\necho crash >&2\nexit 3\n"); fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    pr = subprocess.run(["bash", "-e", "-c", line], capture_output=True, text=True, env={**os.environ, "PATH": f"{d}:{os.environ['PATH']}"}, cwd=d, timeout=30)
assert pr.returncode == 0 and "::warning title=ECB rates::" in pr.stdout, (pr.returncode, pr.stdout, pr.stderr)
print("  ✓ провал → код 0, старият файл остава; в daily_brief.yml — след брифа, преди commit-а; continue-on-error, timeout-minutes 3, || echo ::warning::")
print("\n✅ test_tax_ecb_file: всичко мина")
