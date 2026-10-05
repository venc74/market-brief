"""
Пакет 4б (06.10.2026) · т.з: .github/workflows/daily_brief.yml — преди push на ботовия commit: git pull --rebase с повторен опит (ръчен commit в main по време на run-а иначе отхвърля push-а и
брифът на деня не се качва); NEWS_API_KEY е махнат (NewsAPI не се ползва от 03.10). Тестът ИЗПЪЛНЯВА самия скрипт на стъпката "Commit dashboard + data" (извлечен от yml) срещу временни git
хранилища (bare remote + клонове) — без мрежа, без реалното хранилище.

РЕАЛНО: текстът на workflow файла (скриптът на стъпката е точно този, който ще върви в GitHub Actions; пауза между опитите RETRY_DELAY=0 само в теста). СИНТЕТИЧНО: хранилищата, файловете и
"ръчните" commit-и във временна директория; remote hook, който отхвърля първия push.
Пускане: python test_workflow_push.py
"""
import sys, os, re, atexit, shutil, pathlib, subprocess, tempfile, textwrap
ROOT = pathlib.Path(__file__).parent
YML = (ROOT / ".github" / "workflows" / "daily_brief.yml").read_text(encoding="utf-8")

print("── файлът ──")
live = [l for l in YML.splitlines() if not l.strip().startswith("#")]
assert "NEWS_API_KEY" not in YML and not any(l.strip().startswith("schedule:") for l in live)         # няма NewsAPI; все още няма schedule: тригер (виж CLAUDE.md)
assert "workflow_dispatch" in YML and "CLAUDE_MODEL: claude-sonnet-4-6" in YML and "ANTHROPIC_API_KEY" in YML and "contents: write" in YML
m = re.search(r"      - name: Commit dashboard \+ data\n        run: \|\n((?:          .*\n|\n)+)", YML)
assert m, "стъпката не е намерена"
SCRIPT = textwrap.dedent(m.group(1))
assert "git pull --rebase" in SCRIPT and "for attempt in 1 2 3 4" in SCRIPT and "git rebase --abort" in SCRIPT
print("  ✓ NEWS_API_KEY го няма; няма schedule: тригер; ANTHROPIC/модел/права непипнати; стъпката има pull --rebase и до 4 опита")

ENV = {**{k: v for k, v in os.environ.items() if k in ("PATH", "LANG")}, "GIT_TERMINAL_PROMPT": "0", "RETRY_DELAY": "0", "HOME": tempfile.gettempdir(),
       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}


def sh(cmd, cwd, check=True):
    r = subprocess.run(cmd, cwd=cwd, shell=True, env=ENV, capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"{cmd}\n{r.stdout}{r.stderr}")
    return r


def world(tag):
    """Bare remote + 'runner' (клонът на Actions) + 'human' (втори клон за ръчния commit)."""
    base = pathlib.Path(tempfile.mkdtemp(prefix=f"mb_wf_{tag}_"))
    atexit.register(shutil.rmtree, base, True)
    sh(f"git init -q --bare -b main {base}/remote.git", base)
    sh(f"git clone -q {base}/remote.git {base}/seed", base)
    sh("git -c user.name=u -c user.email=u@x checkout -q -b main", base / "seed", check=False)
    (base / "seed" / "docs").mkdir(); (base / "seed" / "data").mkdir()
    (base / "seed" / "docs" / "index.html").write_text("v0\n"); (base / "seed" / "data" / "a.json").write_text("{}\n"); (base / "seed" / "README.md").write_text("r\n")
    sh("git add -A && git -c user.name=u -c user.email=u@x commit -q -m init && git push -q origin main", base / "seed")
    sh(f"git clone -q {base}/remote.git {base}/runner", base); sh(f"git clone -q {base}/remote.git {base}/human", base)
    return base


def run_step(base):
    return subprocess.run(["bash", "-e", "-c", SCRIPT], cwd=base / "runner", env=ENV, capture_output=True, text=True)


def log(base):
    return sh("git log --format=%s main", base / "remote.git").stdout.split("\n")[:-1]


def manual_commit(base, file, text, msg):
    (base / "human" / file).write_text(text)
    sh(f"git add -A && git -c user.name=h -c user.email=h@x commit -q -m '{msg}' && git push -q origin main", base / "human")


print()
print("── изпълнение на скрипта на стъпката ──")
b = world("a")                                                                          # А) без паралелен commit
(b / "runner" / "docs" / "index.html").write_text("v1\n")
r = run_step(b)
assert r.returncode == 0 and log(b)[0].startswith("brief: ") and log(b)[1] == "init", (r.stdout, r.stderr)
print("  ✓ А) без паралелен commit: commit 'brief: <дата>' и push от първия опит")

b = world("b")                                                                          # Б) ръчен commit в main по време на run-а (друг файл) → push би бил отхвърлен
(b / "runner" / "docs" / "index.html").write_text("v1\n"); (b / "runner" / "data" / "b.json").write_text("{}\n")
manual_commit(b, "README.md", "ръчна промяна\n", "ръчен commit по време на run-а")
plain = subprocess.run("git add docs/ data/ && git -c user.name=b -c user.email=b@x commit -q -m probe && git push", cwd=b / "runner", shell=True, env=ENV, capture_output=True, text=True)
assert plain.returncode != 0 and "rejected" in plain.stderr                              # КОНТРОЛ: старият 'git push' пада
sh("git reset -q --hard origin/main", b / "runner")
(b / "runner" / "docs" / "index.html").write_text("v1\n"); (b / "runner" / "data" / "b.json").write_text("{}\n")
r = run_step(b)
L = log(b)
assert r.returncode == 0 and L[0].startswith("brief: ") and L[1] == "ръчен commit по време на run-а" and L[2] == "init", (L, r.stdout, r.stderr)
assert "Merge" not in "".join(log(b)) and len(L) == 3                                    # линейна история: rebase, не merge
print("  ✓ Б) КОНТРОЛ: старият 'git push' се отхвърля ('rejected'); новата стъпка: pull --rebase и push — ръчният commit е запазен, ботовият е отгоре, историята е линейна")

b = world("c")                                                                          # В) пропуснат push веднъж (remote hook отхвърля първия опит) → успява на втория
hook = b / "remote.git" / "hooks" / "pre-receive"
hook.write_text(f"#!/bin/sh\nc={b}/count\nn=$(cat $c 2>/dev/null || echo 0)\necho $((n+1)) > $c\n[ $n -eq 0 ] && {{ echo 'временен отказ' >&2; exit 1; }}\nexit 0\n")
hook.chmod(0o755)
(b / "runner" / "docs" / "index.html").write_text("v1\n")
r = run_step(b)
assert r.returncode == 0 and "опит 1 от 4 неуспешен" in r.stdout and log(b)[0].startswith("brief: "), (r.stdout, r.stderr)
print("  ✓ В) временно отхвърлен push: опит 1 неуспешен, опит 2 минава (видимо в лога)")

b = world("d")                                                                          # Г) конфликт при rebase (ръчна промяна на СЪЩИЯ файл) → 4 опита, видима грешка, без недовършен rebase
(b / "runner" / "docs" / "index.html").write_text("ботова версия\n")
manual_commit(b, "docs/index.html", "ръчна версия\n", "ръчна промяна на index.html")
r = run_step(b)
assert r.returncode == 1 and r.stdout.count("неуспешен — повторен опит") == 4 and "::error::commit-ът на брифа не успя да се качи след 4 опита" in r.stdout
assert log(b)[0] == "ръчна промяна на index.html"                                       # remote е недокоснат
st = sh("git status", b / "runner").stdout
assert "rebase in progress" not in st and "You are currently rebasing" not in st
print("  ✓ Г) конфликт на същия файл: 4 опита, '::error::…' и код 1 (стъпката пада видимо), remote е недокоснат, няма недовършен rebase")

b = world("e")                                                                          # Д) няма промени → няма commit, стъпката е успешна
r = run_step(b)
assert r.returncode == 0 and log(b) == ["init"]
print("  ✓ Д) без промени: няма commit и няма грешка")
print()
print("Всички тестове минаха.")
