"""
Пакет 4а · т.10 (2026-10-03): самият run_tests.py — секретите се чистят, мрежата е забранена, запис в docs/ или
data/ е провал, ненулев изход при провал. Всичко е СИНТЕТИЧНО (временни папки и малки тестови скриптове).
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
write("test_fails.py", "raise SystemExit(3)\n")
code, out = run()
assert code == 1 and "FAIL test_fails" in out and "1 провал" in out
code, out = run("test_ok")                                                              # филтър по име
assert code == 0 and "test_fails" not in out
code, out = run("няма-такъв")
assert code == 1 and "няма тестове" in out
print("  ✓ запис в docs/ или нов файл в data/ → провал с името на файла; опит за мрежа → провал; ненулев тест → код 1; филтър по име")
tmp.cleanup()

print()
print("Всички тестове минаха.")
