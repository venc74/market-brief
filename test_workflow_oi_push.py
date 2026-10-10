"""
К1 (втори преглед, 10.10.2026) · .github/workflows/oi_snapshot.yml — стъпката "Commit snapshot" падаше от 09.10: снимката (UOV кошницата, 08.10) пише и кешовете, които git
следи (data/unusual_options_volume_rank_cache.json, data/sp500_ndx_universe.json), а стъпката add-ваше само снимката → "cannot pull with rebase: You have unstaged changes",
код 128 (run 37955976842; последната сесия в снимката остана 08.10). Тестът ИЗПЪЛНЯВА скрипта на стъпката (извлечен от yml) срещу временни git хранилища — без мрежа, без
реалното хранилище. Изпълнява и СТАРИЯ скрипт (от origin/main преди поправката, вграден тук буквално) като контрол, че пада точно с тази грешка.

РЕАЛНО: текстът на workflow файла; имената на двата кеша и на снимката (същите като в data/). СИНТЕТИЧНО: хранилищата, съдържанието на файловете, "замърсеният" кеш,
паралелният commit на брифа и remote hook-ът. Пауза между опитите RETRY_DELAY=0 само в теста.
Пускане: python test_workflow_oi_push.py
"""
import os, re, atexit, shutil, pathlib, subprocess, tempfile, textwrap
ROOT = pathlib.Path(__file__).parent
YML = (ROOT / ".github" / "workflows" / "oi_snapshot.yml").read_text(encoding="utf-8")

m = re.search(r"      - name: Commit snapshot\n        run: \|\n((?:          .*\n|\n)+)", YML)
assert m, "стъпката не е намерена"
SCRIPT = textwrap.dedent(m.group(1))
# старият скрипт (aec921b) — дословно
OLD = textwrap.dedent("""\
    git config user.name "brief-bot"
    git config user.email "actions@github.com"
    git add data/unusual_options_oi_snapshot.json 2>/dev/null || true
    git diff --cached --quiet && exit 0
    git commit -m "oi snapshot: $(date -u +%F)"
    git pull --rebase
    git push
    """)
SNAP, RANK, UNIV = "data/unusual_options_oi_snapshot.json", "data/unusual_options_volume_rank_cache.json", "data/sp500_ndx_universe.json"

print("── файлът ──")
assert "for attempt in 1 2 3 4" in SCRIPT and "git rebase --abort" in SCRIPT and "git stash push --include-untracked" in SCRIPT
assert SCRIPT.index("git stash push") < SCRIPT.index("git pull --rebase")
assert "git add data/unusual_options_oi_snapshot.json" in SCRIPT and "git add data/\n" not in SCRIPT and "git add -A" not in SCRIPT   # кешовете НЕ се качват оттук
live = [l for l in YML.splitlines() if not l.strip().startswith("#")]
assert any(l.strip() == "group: daily-brief" for l in live) and 'cron: "0 15 * * 1-5"' in YML and "workflow_dispatch" in YML
print("  ✓ stash -u преди pull --rebase, до 4 опита, само снимката се add-ва; обща concurrency група, cron и dispatch непипнати")

ENV = {**{k: v for k, v in os.environ.items() if k in ("PATH", "LANG")}, "GIT_TERMINAL_PROMPT": "0", "RETRY_DELAY": "0", "HOME": tempfile.gettempdir(),
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def sh(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=cwd, shell=True, env=ENV, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"{cmd}\n{r.stdout}{r.stderr}")
    return r


def world(tag):
    """Bare remote с трите следени файла + 'runner' (Actions) + 'brief' (паралелният бриф/ръчен commit)."""
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"mb_oi_{tag}_"))
    atexit.register(shutil.rmtree, base, True)
    sh(f"git init -q --bare -b main {base}/remote.git", base)
    sh(f"git clone -q {base}/remote.git {base}/seed", base)
    sh("git checkout -q -b main", base / "seed", check=False)
    (base / "seed" / "data").mkdir()
    for f in (SNAP, RANK, UNIV):
        (base / "seed" / f).write_text('{"date": "2026-10-08"}\n')
    sh("git add -A && git -c user.name=u -c user.email=u@x commit -q -m init && git push -q origin main", base / "seed")
    sh(f"git clone -q {base}/remote.git {base}/runner", base); sh(f"git clone -q {base}/remote.git {base}/brief", base)
    return base


def snapshot_run(base):
    """Какво прави python src/oi_snapshot.py на диска: нова снимка + ЗАМЪРСЕНИ кешове (кошницата) + неследен временен файл."""
    (base / "runner" / SNAP).write_text('{"snapshots": {"2026-10-09": {}}}\n')
    (base / "runner" / RANK).write_text('{"date": "2026-10-09", "ranked": ["NVDA"]}\n')
    (base / "runner" / UNIV).write_text('{"date": "2026-10-09"}\n')
    (base / "runner" / "data" / "tmp_scratch.json").write_text("{}\n")


def run(base, script):
    return subprocess.run(["bash", "-e", "-c", script], cwd=base / "runner", env=ENV, capture_output=True, text=True)


def log(base):
    return sh("git log --format=%s main", base / "remote.git").stdout.split("\n")[:-1]


def remote_file(base, f):
    return sh(f"git show main:{f}", base / "remote.git").stdout


print()
print("── КОНТРОЛ: старият скрипт срещу замърсен кеш ──")
b = world("old")
snapshot_run(b)
r = run(b, OLD)
assert r.returncode != 0 and "unstaged changes" in (r.stdout + r.stderr) and log(b) == ["init"], (r.stdout, r.stderr)
print("  ✓ старият скрипт пада с 'cannot pull with rebase: You have unstaged changes' и снимката НЕ стига до remote (както на 09.10)")

print()
print("── новият скрипт ──")
b = world("a")                                                                          # А) замърсен кеш, без паралелен commit
snapshot_run(b)
r = run(b, SCRIPT)
assert r.returncode == 0 and log(b)[0].startswith("oi snapshot: ") and log(b)[1] == "init", (r.stdout, r.stderr)
assert "2026-10-09" in remote_file(b, SNAP) and remote_file(b, RANK) == '{"date": "2026-10-08"}\n' and remote_file(b, UNIV) == '{"date": "2026-10-08"}\n'
assert "tmp_scratch.json" not in sh("git ls-tree -r --name-only main", b / "remote.git").stdout
print("  ✓ А) замърсен кеш: снимката е качена от първия опит; кешовете и неследеният файл НЕ са качени")

b = world("b")                                                                          # Б) замърсен кеш + бриф commit-нал СЪЩИТЕ кешове междувременно
snapshot_run(b)
(b / "brief" / RANK).write_text('{"date": "2026-10-09", "ranked": ["AAPL"]}\n'); (b / "brief" / "data" / "2026-10-09.json").write_text("{}\n")
sh("git add -A && git -c user.name=b -c user.email=b@x commit -q -m 'brief: 2026-10-09' && git push -q origin main", b / "brief")
r = run(b, SCRIPT)
L = log(b)
assert r.returncode == 0 and L[0].startswith("oi snapshot: ") and L[1] == "brief: 2026-10-09" and L[2] == "init" and "Merge" not in "".join(L), (L, r.stdout, r.stderr)
assert '"AAPL"' in remote_file(b, RANK)                                                # кешът на брифа е запазен, не е презаписан от снимката
print("  ✓ Б) паралелен commit на брифа със СЪЩИЯ кеш: без конфликт, линейна история, кешът на брифа е запазен")

b = world("c")                                                                          # В) временно отхвърлен push → успява на втория опит
hook = b / "remote.git" / "hooks" / "pre-receive"
hook.write_text(f"#!/bin/sh\nc={b}/count\nn=$(cat $c 2>/dev/null || echo 0)\necho $((n+1)) > $c\n[ $n -eq 0 ] && {{ echo 'временен отказ' >&2; exit 1; }}\nexit 0\n")
hook.chmod(0o755)
snapshot_run(b)
r = run(b, SCRIPT)
assert r.returncode == 0 and "опит 1 от 4 неуспешен" in r.stdout and log(b)[0].startswith("oi snapshot: "), (r.stdout, r.stderr)
print("  ✓ В) временно отхвърлен push: опит 1 неуспешен, опит 2 минава (видимо в лога)")

b = world("d")                                                                          # Г) конфликт на самата снимка → 4 опита, видима грешка, без недовършен rebase
snapshot_run(b)
(b / "brief" / SNAP).write_text('{"ръчно": true}\n')
sh("git add -A && git -c user.name=h -c user.email=h@x commit -q -m 'ръчна промяна на снимката' && git push -q origin main", b / "brief")
r = run(b, SCRIPT)
assert r.returncode == 1 and r.stdout.count("неуспешен — повторен опит") == 4 and "::error::OI снимката не успя да се качи след 4 опита" in r.stdout
st = sh("git status", b / "runner").stdout
assert log(b)[0] == "ръчна промяна на снимката" and "rebase in progress" not in st and "You are currently rebasing" not in st
print("  ✓ Г) конфликт на снимката: 4 опита, '::error::…' и код 1, remote недокоснат, няма недовършен rebase")

b = world("e")                                                                          # Д) същата снимка (сесията вече е записана) → няма commit, кешовете не пречат
(b / "runner" / RANK).write_text('{"date": "2026-10-09"}\n')
r = run(b, SCRIPT)
assert r.returncode == 0 and log(b) == ["init"]
print("  ✓ Д) без нова снимка (само замърсен кеш): няма commit и няма грешка")
print()
print("Всички тестове минаха.")
