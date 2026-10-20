"""
Пакет 4а · т.10 (2026-10-03): самият run_tests.py — секретите се чистят, мрежата е забранена, запис в docs/ или
data/ е провал, ненулев изход при провал; 20.10.2026 (етап 3б) — и ЧЕТЕНЕ на data/ и docs/data/, временни папки за всеки тест. Всичко е СИНТЕТИЧНО (временни папки и малки тестови скриптове).
Пускане: python test_ci_guard.py (или през python run_tests.py)
"""
import sys, pathlib, tempfile, socket, subprocess, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import run_tests

print("── секретите се чистят от средата на тестовете ──")
env = run_tests.clean_env({"PATH": "/usr/bin", "ANTHROPIC_API_KEY": "sk-x", "FRED_API_KEY": "f", "GMAIL_APP_PASSWORD": "p",
                           "TRADIER_API_KEY": "t", "EDGAR_UA": "me@example.com", "GITHUB_TOKEN": "g", "MY_SECRET": "s",
                           "MODEL_PROBE_MAX_TOKENS": "16", "ENABLE_NEWS": "0"})
assert not any(k in env for k in ("ANTHROPIC_API_KEY", "FRED_API_KEY", "GMAIL_APP_PASSWORD", "TRADIER_API_KEY", "EDGAR_UA", "GITHUB_TOKEN", "MY_SECRET"))
assert env["MODEL_PROBE_MAX_TOKENS"] == "16" and env["ENABLE_NEWS"] == "0" and env["PATH"] == "/usr/bin"       # конфигурацията остава
assert str(run_tests.GUARD) in env["PYTHONPATH"].split(":")
print("  ✓ API ключове, пароли, EDGAR_UA, GITHUB_TOKEN и *_SECRET се махат; обикновените настройки остават")

print("── прокситата не стигат до тестовете (втори преглед, 10.10) ──")
env = run_tests.clean_env({"PATH": "/usr/bin", "HTTPS_PROXY": "http://127.0.0.1:3128", "http_proxy": "http://127.0.0.1:3128", "ALL_PROXY": "socks5://127.0.0.1:1080",
                           "NO_PROXY": "localhost", "ENABLE_NEWS": "0"})
assert not any(k.lower().endswith("_proxy") for k in env) and env["ENABLE_NEWS"] == "0"
r = subprocess.run([sys.executable, "-c", "import os; print(sorted(k for k in os.environ if k.lower().endswith('proxy')))"],
                   env={**run_tests.clean_env(), "HTTPS_PROXY": "http://127.0.0.1:3128"}, capture_output=True, text=True, timeout=30)
assert r.returncode == 0 and r.stdout.strip() == "[]", r.stdout + r.stderr                  # sitecustomize ги маха и при директно пускане
print("  ✓ HTTPS_PROXY/http_proxy/ALL_PROXY/NO_PROXY се махат от средата; sitecustomize маха прокси, подадено отвън (иначе 127.0.0.1-прокси тунелира навън)")

print("── мрежата е забранена, loopback работи ──")
env = run_tests.clean_env()
r = subprocess.run([sys.executable, "-c", "import socket; socket.create_connection(('1.1.1.1', 80), timeout=2)"],
                   env=env, capture_output=True, text=True, timeout=30)
assert r.returncode != 0 and "тест към мрежата е забранен" in r.stderr, r.stderr[-300:]
r = subprocess.run([sys.executable, "-c", "import requests; requests.get('https://api.anthropic.com/v1/messages', timeout=2)"],
                   env=env, capture_output=True, text=True, timeout=30)
assert r.returncode != 0 and "забранен" in r.stderr                                    # и през requests (Claude API)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
port = srv.getsockname()[1]
r = subprocess.run([sys.executable, "-c", f"import socket; socket.create_connection(('127.0.0.1', {port}), timeout=5).close(); print('ok')"],
                   env=env, capture_output=True, text=True, timeout=30)
srv.close()
assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-300:]
print("  ✓ връзка към 1.1.1.1 и към api.anthropic.com (през requests) гърми веднага; loopback минава")

print("── runner-ът: запис в docs/ или data/ и мрежа са провал ──")
tmp = tempfile.TemporaryDirectory(prefix="market_brief_runner_")
T = pathlib.Path(tmp.name)
(T / "docs").mkdir(); (T / "data").mkdir()
(T / "docs" / "index.html").write_text("стар"); (T / "data" / "x.json").write_text("{}")
run_tests.ROOT = T


def write(name, body):
    (T / name).write_text(body, encoding="utf-8")


def run(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = run_tests.main(list(args))
    return code, out.getvalue()


write("test_ok.py", "print('ok')\n")
code, out = run()
assert code == 0 and "OK   test_ok" in out and "1/1 теста минават" in out
write("test_writes_docs.py", "import pathlib; pathlib.Path('docs/index.html').write_text('нов')\n")
code, out = run()
assert code == 1 and "docs/index.html" in out and "docs/data са пипнати" in out
(T / "test_writes_docs.py").unlink(); (T / "docs" / "index.html").write_text("стар")
write("test_new_data.py", "import pathlib; pathlib.Path('data/new.json').write_text('{}')\n")
code, out = run()
assert code == 1 and "data/new.json" in out
(T / "test_new_data.py").unlink(); (T / "data" / "new.json").unlink()
write("test_net.py", "import socket; socket.create_connection(('8.8.8.8', 53), timeout=2)\n")
code, out = run()
assert code == 1 and "FAIL test_net" in out and "забранен" in out
(T / "test_net.py").unlink()
write("test_reads_data.py", "import pathlib; pathlib.Path('data/x.json').read_text()\n")                 # 20.10.2026 (етап 3б): четене на реалните данни е провал
code, out = run()
assert code == 1 and "FAIL test_reads_data" in out and "тестът чете реалните данни" in out and "data/x.json" in out
(T / "test_reads_data.py").unlink()
(T / "docs" / "data").mkdir(); (T / "docs" / "data" / "2026-10-20.json").write_text("{}")
write("test_reads_briefs.py", "import json, pathlib; json.loads(pathlib.Path('docs/data/2026-10-20.json').read_text())\n")
code, out = run("test_reads_briefs")
assert code == 1 and "docs/data/2026-10-20.json" in out
(T / "test_reads_briefs.py").unlink()
write("test_reads_index.py", "import pathlib; pathlib.Path('docs/index.html').read_text()\n")              # docs/index.html не е данни (само docs/data/ и data/)
code, out = run("test_reads_index")
assert code == 0, out
(T / "test_reads_index.py").unlink()
write("test_tmp_dirs.py", "import os, pathlib; d = pathlib.Path(os.environ['MB_DATA_DIR']); assert d.is_dir() and 'data' == d.name and str(d) != str(pathlib.Path('data').resolve()); "
                          "(d / 'state.json').write_text('{}'); assert pathlib.Path(os.environ['MB_DOCS_DIR']).is_dir()\n")
code, out = run("test_tmp_dirs")
assert code == 0 and not (T / "data" / "state.json").exists(), out                                       # пише във временната data/, не в реалната
(T / "test_tmp_dirs.py").unlink()
env_t = run_tests.test_env({"PATH": "/usr/bin"}, pathlib.Path(tempfile.mkdtemp()))
assert {"MB_DATA_DIR", "MB_DOCS_DIR", "MB_GUARD_ROOT", "MB_TEST_READ_LOG"} <= set(env_t) and "BG_VOCAB_FILE" not in env_t     # в T няма замразен речник
print("  ✓ СИНТЕТИЧНО: четене на data/ или docs/data/ → провал с името на файла; docs/index.html — разрешено; всеки тест има временни MB_DATA_DIR / MB_DOCS_DIR")
write("test_fails.py", "raise SystemExit(3)\n")
code, out = run()
assert code == 1 and "FAIL test_fails" in out and "1 провал" in out
code, out = run("test_ok")                                                              # филтър по име
assert code == 0 and "test_fails" not in out
code, out = run("няма-такъв")
assert code == 1 and "няма тестове" in out
print("  ✓ запис в docs/ или нов файл в data/ → провал с името на файла; опит за мрежа → провал; ненулев тест → код 1; филтър по име")
print("── анотации за GitHub Actions (08.10): причината за червен run се чете без вход ──")
ann = run_tests.annotations([("test_x", "ред 1\nAssertionError: 100% грешка\r\nкрай"), ("test_y", "a" * 5000)], ["data/new.json", "docs/index.html"])
assert ann[0] == "::error title=Test test_x::ред 1%0AAssertionError: 100%25 грешка%0D%0Aкрай"
assert ann[1].startswith("::error title=Test test_y::") and len(ann[1]) == len("::error title=Test test_y::") + 1200 and "\n" not in ann[1]
assert ann[2] == "::error title=docs/data са пипнати::data/new.json, docs/index.html" and run_tests.annotations([], []) == []
import os
write("test_fails2.py", "raise SystemExit(3)\n")
os.environ["GITHUB_ACTIONS"] = "true"
try:
    code, out = run("test_fails2")
finally:
    del os.environ["GITHUB_ACTIONS"]
assert code == 1 and "::error title=Test test_fails2::" in out
code, out = run("test_fails2")
assert code == 1 and "::error" not in out                                                  # извън GitHub Actions не се печата нищо допълнително
(T / "test_fails2.py").unlink()
print("  ✓ СИНТЕТИЧНО: %, CR и LF са екранирани; изходът се реже до последните 1200 знака; пипнатите папки са отделна анотация; печата се само при GITHUB_ACTIONS=true")
tmp.cleanup()

print()
print("Всички тестове минаха.")
