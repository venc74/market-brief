"""
12.10.2026 · oi_snapshot.yml в СОБСТВЕНА concurrency група (не "daily-brief") — OI run не може да отмени чакащ бриф; едновременно качване на двата job-а се покрива от
повторните опити: OI — stash + pull --rebase (commit-ва се само снимката), брифът — pull --rebase (docs/ и data/; снимката само я чете). Тестът чете двата yml и ИЗПЪЛНЯВА
стъпките им за commit/push (извлечени дословно) срещу временни git хранилища — без мрежа и без реалното хранилище.

РЕАЛНО: текстът на двата workflow файла; имената на снимката и на кешовете (както в data/). СИНТЕТИЧНО: хранилищата и съдържанието на файловете. Паузата между опитите
RETRY_DELAY=1 само в теста.
Пускане: python test_workflow_concurrency.py
"""
import os, re, atexit, shutil, pathlib, subprocess, tempfile, textwrap
ROOT = pathlib.Path(__file__).parent
WF = ROOT / ".github" / "workflows"
OI_YML, BRIEF_YML = (WF / "oi_snapshot.yml").read_text(encoding="utf-8"), (WF / "daily_brief.yml").read_text(encoding="utf-8")


def step(yml, name):
    m = re.search(r"      - name: " + re.escape(name) + r"\n        run: \|\n((?:          .*\n|\n)+)", yml)
    assert m, name
    return textwrap.dedent(m.group(1))


def group(yml):
    live = "\n".join(l for l in yml.splitlines() if not l.strip().startswith("#"))
    m = re.search(r"^concurrency:\n  group: (\S+)\n  cancel-in-progress: (\w+)", live, re.M)
    return m.group(1), m.group(2)


OI, BRIEF = step(OI_YML, "Commit snapshot"), step(BRIEF_YML, "Commit dashboard + data")
SNAP, RANK, UNIV = "data/unusual_options_oi_snapshot.json", "data/unusual_options_volume_rank_cache.json", "data/sp500_ndx_universe.json"

print("── 1. групите и повторните опити (от yml) ──")
assert group(BRIEF_YML) == ("daily-brief", "false") and group(OI_YML) == ("oi-snapshot", "false")
for s in (OI, BRIEF):
    assert "for attempt in 1 2 3 4" in s and "git pull --rebase && git push" in s and "git rebase --abort" in s and "exit 1" in s
assert "git add data/unusual_options_oi_snapshot.json" in OI and "git stash push --include-untracked" in OI and OI.index("git stash push") < OI.index("git pull --rebase")
assert "git add docs/ data/" in BRIEF
print("  ✓ брифът: група 'daily-brief'; OI: собствена 'oi-snapshot' (без отменяне на текущия run и в двете); и двата: pull --rebase + push с до 4 опита и rebase --abort")

ENV = {**{k: v for k, v in os.environ.items() if k in ("PATH", "LANG")}, "GIT_TERMINAL_PROMPT": "0", "RETRY_DELAY": "1", "HOME": tempfile.gettempdir(),
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def sh(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=cwd, shell=True, env=ENV, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"{cmd}\n{r.stdout}{r.stderr}")
    return r


def world(tag):
    """Bare remote + два runner-а с ЕДНА И СЪЩА база (клонирани преди който и да е push — това е едновременното качване)."""
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"mb_conc_{tag}_"))
    atexit.register(shutil.rmtree, base, True)
    sh(f"git init -q --bare -b main {base}/remote.git", base)
    sh(f"git clone -q {base}/remote.git {base}/seed", base)
    sh("git checkout -q -b main", base / "seed", check=False)
    (base / "seed" / "data").mkdir(); (base / "seed" / "docs").mkdir()
    for f in (SNAP, RANK, UNIV, "docs/index.html"):
        (base / "seed" / f).write_text("init\n")
    sh("git add -A && git -c user.name=u -c user.email=u@x commit -q -m init && git push -q origin main", base / "seed")
    for r in ("brief", "oi"):
        sh(f"git clone -q {base}/remote.git {base}/{r}", base)
    # какво оставят на диска двата run-а
    (base / "brief" / "docs" / "index.html").write_text("brief 12.10\n"); (base / "brief" / "data" / "2026-10-12.json").write_text("{}\n")
    (base / "brief" / RANK).write_text("brief cache\n"); (base / "brief" / UNIV).write_text("brief universe\n")
    (base / "oi" / SNAP).write_text('{"snapshots": {"2026-10-12": {}}}\n')
    (base / "oi" / RANK).write_text("oi cache\n"); (base / "oi" / UNIV).write_text("oi universe\n")              # кешовете на OI — настрана (stash), не се качват
    return base


def run(base, who, script):
    return subprocess.run(["bash", "-e", "-c", script], cwd=base / who, env=ENV, capture_output=True, text=True)


def check(base, tag):
    L = sh("git log --format=%s main", base / "remote.git").stdout.split("\n")[:-1]
    show = lambda f: sh(f"git show main:{f}", base / "remote.git").stdout
    assert len(L) == 3 and L[-1] == "init" and any(x.startswith("brief: ") for x in L) and any(x.startswith("oi snapshot: ") for x in L) and not any("Merge" in x for x in L), (tag, L)
    assert "2026-10-12" in show(SNAP) and show("docs/index.html") == "brief 12.10\n" and show(RANK) == "brief cache\n" and show(UNIV) == "brief universe\n", tag
    return L


print()
print("── 2. едновременно качване (обща база), в двата реда ──")
b = world("brief_first")
r1 = run(b, "brief", BRIEF); r2 = run(b, "oi", OI)
assert r1.returncode == 0 and r2.returncode == 0, (r1.stdout + r1.stderr, r2.stdout + r2.stderr)
L = check(b, "brief_first")
print(f"  ✓ брифът качва първи, OI (остаряла база) → stash + pull --rebase + push: {L[0]} над {L[1]}; кешовете на брифа остават, снимката е на OI")
b = world("oi_first")
r1 = run(b, "oi", OI); r2 = run(b, "brief", BRIEF)
assert r1.returncode == 0 and r2.returncode == 0, (r1.stdout + r1.stderr, r2.stdout + r2.stderr)
L = check(b, "oi_first")
print(f"  ✓ OI качва първи, брифът (остаряла база) → pull --rebase + push: {L[0]} над {L[1]}; линейна история, без конфликт")

print()
print("── 3. наистина паралелно (5 кръга) ──")
for k in range(5):
    b = world(f"par{k}")
    pa = subprocess.Popen(["bash", "-e", "-c", BRIEF], cwd=b / "brief", env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pb = subprocess.Popen(["bash", "-e", "-c", OI], cwd=b / "oi", env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    oa, ob = pa.communicate(timeout=120), pb.communicate(timeout=120)
    assert pa.returncode == 0 and pb.returncode == 0, (oa, ob)
    check(b, f"par{k}")
print("  ✓ двата скрипта, пуснати едновременно: и двата качват всеки път, история от 3 commit-а без merge, файловете на всеки job са на мястото си")
print()
print("Всички тестове минаха.")
