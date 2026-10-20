#!/usr/bin/env python3
"""
Пуска всички test_*.py (всеки в собствен процес) — локално и в CI (.github/workflows/tests.yml).
Пакет 4а · т.10 (2026-10-03). Гарантира три неща:
  1. БЕЗ МРЕЖА и без платени API: ключовете/паролите се чистят от средата, а tests/_nonet/sitecustomize.py
     забранява връзки извън loopback — Claude/Yahoo/SEC извикване в тест гърми, не харчи пари;
  2. БЕЗ ЗАПИС в docs/ и data/: преди и след се снема отпечатък на двете папки (пътища + sha1); разлика = провал
     (докладва кои файлове са променени);
  3. ненулев изход при провал на който и да е тест;
  4. (20.10.2026, етап 3б) БЕЗ ЧЕТЕНЕ на реалните данни: всеки тест получава временни data/ и docs/ (MB_DATA_DIR / MB_DOCS_DIR → config.DATA_DIR / DOCS_DIR и всички пътища от тях),
     замразения речник на езиковия филтър (BG_VOCAB_FILE) и дневник на отварянията под data/ и docs/data/ (tests/_nonet/sitecustomize.py) — отваряне там = провал.
Употреба: python run_tests.py [част-от-име ...]   (напр. python run_tests.py trade_sim escape)
"""
from __future__ import annotations
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).parent
GUARD = ROOT / "tests" / "_nonet"
GUARDED_DIRS = ("docs", "data")
TIMEOUT = 300
VOCAB_FIXTURE = pathlib.Path("tests") / "fixtures" / "bg_vocab_2026-10-20.json"      # замразеният речник (РЕАЛЕН — от 89-те публикувани брифа до 20.10)
_SECRET_RE = re.compile(r"(_API_KEY|PASSWORD|SECRET)$")
_SECRET_NAMES = {"GITHUB_TOKEN", "EDGAR_UA", "GMAIL_USER"}
# втори преглед (10.10.2026): прокси на loopback (HTTPS_PROXY=http://127.0.0.1:…) заобикаляше защитата — връзката е към 127.0.0.1 (разрешено), а проксито
# тунелира към data.sec.gov (CONNECT); test_13f_real/test_dataroma правеха 7 такива заявки, грешката се поглъщаше. Прокситата не стигат до тестовете.
_PROXY_RE = re.compile(r"^(https?|all|ftp|no)_proxy$", re.I)


def clean_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Средата за тестовия процес: без секрети, с мрежовата защита в PYTHONPATH."""
    src = dict(os.environ if env is None else env)
    out = {k: v for k, v in src.items() if k not in _SECRET_NAMES and not _SECRET_RE.search(k) and not _PROXY_RE.search(k)}
    out["PYTHONPATH"] = os.pathsep.join(filter(None, [str(GUARD), str(ROOT), out.get("PYTHONPATH", "")]))
    out["PYTHONDONTWRITEBYTECODE"] = "1"
    return out


def test_env(env: dict[str, str], tmp: pathlib.Path) -> dict[str, str]:
    """
    Средата на ЕДИН тестов процес (20.10.2026, етап 3б): временни data/ и docs/ в tmp, коренът за дневника на четенията, самият дневник и замразеният речник (ако го има в ROOT).
    До 20.10 7 теста четяха реални файлове в data/ (tracker-а, кешове, състояния), а 25 — публикуваните брифове в docs/data/ (речника на езиковия филтър).
    """
    (tmp / "data").mkdir(exist_ok=True)
    (tmp / "docs").mkdir(exist_ok=True)
    out = {**env, "MB_DATA_DIR": str(tmp / "data"), "MB_DOCS_DIR": str(tmp / "docs"), "MB_GUARD_ROOT": str(ROOT.resolve()), "MB_TEST_READ_LOG": str(tmp / "reads.log")}
    vocab = ROOT / VOCAB_FIXTURE
    if vocab.exists():
        out["BG_VOCAB_FILE"] = str(vocab)
    return out


def guarded_reads(tmp: pathlib.Path) -> list[str]:
    """Реалните файлове под data/ и docs/data/, които тестът е отворил (от дневника на sitecustomize), относително към ROOT."""
    log = tmp / "reads.log"
    if not log.exists():
        return []
    root = str(ROOT.resolve()) + os.sep
    return sorted({l[len(root):] if l.startswith(root) else l for l in log.read_text(encoding="utf-8").split("\n") if l})


def fingerprint(root: pathlib.Path | None = None, dirs=GUARDED_DIRS) -> dict[str, str]:
    """{относителен път: sha1} за всички файлове в защитените папки."""
    root = root or ROOT
    fp = {}
    for d in dirs:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                fp[str(p.relative_to(root))] = hashlib.sha1(p.read_bytes()).hexdigest()
    return fp


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted({*before, *after} - {k for k in before if before.get(k) == after.get(k)})


def _escape_data(text: str) -> str:
    """Екраниране на съобщение на GitHub workflow команда (::error::…): %, CR, LF."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(failures: list[tuple[str, str]], touched: list[str], tail: int = 1200) -> list[str]:
    """
    GitHub Actions анотации (08.10.2026): редовете "::error title=…::…" за всеки провален тест (последните `tail` знака от изхода му) и за пипнатите docs/ и data/. Причина: логът на run-а се чете само
    след вход в GitHub, а анотациите са видими и през публичния API (check-runs/<id>/annotations) — на 08.10 червеният Tests run не можеше да се прочете отстрани. Чиста функция; печата се само в CI.
    """
    out = [f"::error title=Test {name}::{_escape_data(text.strip()[-tail:])}" for name, text in failures]
    if touched:
        out.append(f"::error title=docs/data са пипнати::{_escape_data(', '.join(touched[:20]))}")
    return out


def discover(patterns: list[str]) -> list[pathlib.Path]:
    tests = sorted(ROOT.glob("test_*.py"))     # ROOT се чете при извикване (подменяем в теста на самия runner)
    return [t for t in tests if not patterns or any(p in t.stem for p in patterns)]


def main(argv: list[str]) -> int:
    tests = discover(argv)
    if not tests:
        print("няма тестове за пускане")
        return 1
    env = clean_env()
    before = fingerprint()
    failures, started = [], time.time()
    for t in tests:
        t0 = time.time()
        with tempfile.TemporaryDirectory(prefix="mb_test_") as td:
            tmp = pathlib.Path(td)
            try:
                r = subprocess.run([sys.executable, str(t)], cwd=t.parent, env=test_env(env, tmp), capture_output=True, text=True, timeout=TIMEOUT)
                ok, out = r.returncode == 0, (r.stdout + r.stderr)
            except subprocess.TimeoutExpired as e:
                ok, out = False, f"таймаут след {TIMEOUT}s\n{e.stdout or ''}"
            reads = guarded_reads(tmp)
        if reads:
            ok = False
            out += ("\n✗ тестът чете реалните данни (data/ и docs/data/ се ротират — ползвай fixture или временна папка): "
                    + ", ".join(reads[:10]) + (f" … (+{len(reads) - 10})" if len(reads) > 10 else ""))
        print(f"{'OK  ' if ok else 'FAIL'} {t.stem:<28} {time.time() - t0:5.1f}s")
        if not ok:
            failures.append((t.stem, out))
    touched = changed(before, fingerprint())
    for name, out in failures:
        print(f"\n━━ {name} ━━\n{out[-3000:]}")
    if touched:
        print("\n✗ тестовете са променили защитени папки (docs/ и data/ не бива да се пишат):")
        for p in touched[:20]:
            print("   ", p)
    print(f"\n{len(tests) - len(failures)}/{len(tests)} теста минават за {time.time() - started:.0f}s"
          + (f"; {len(failures)} провал(а)" if failures else "") + ("; docs/data са пипнати" if touched else ""))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for line in annotations(failures, touched):
            print(line)
    return 1 if (failures or touched) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
