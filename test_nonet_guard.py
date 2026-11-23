"""
20.10.2026 · етап 3: защитата на тестовете от мрежа (tests/_nonet/sitecustomize.py) спира и curl_cffi. yfinance тегли през curl_cffi (libcurl отваря сокетите в C) и
заобикаляше проверката на socket: на 20.10 под защитата socket.create_connection('finance.yahoo.com') беше спрян, а yf.Ticker('SPY').history(period='5d') върна 5 живи бара.
Два теста са теглили от Yahoo, без да зависят от резултата (test_book_entry_volume — отчетите в обобщението; test_health_monitor — проверката за сплит) — вече подменени.
Преброено с дневник на опитите върху целия набор: 2 опита преди, 0 след.

СИНТЕТИЧНО: заявките към example.com (не излизат — спират се преди мрежата).
Пускане: python test_nonet_guard.py
"""
import sys as _nsys, pathlib as _npl; _nsys.path.insert(0, str(_npl.Path(__file__).resolve().parent / "tests" / "_nonet")); import nonet_guard  # noqa: E402,F401 — 23.11.2026: без мрежа и без тайни и при „python test_x.py“
import sys, os, pathlib, subprocess
ROOT = pathlib.Path(__file__).parent

PROBE = r'''
import socket
try:
    socket.create_connection(("example.com", 443), timeout=3); print("socket: OPEN")
except RuntimeError as e:
    print("socket: blocked" if "забранен" in str(e) else f"socket: other {e}")
except Exception as e:
    print(f"socket: other {type(e).__name__}")
try:
    from curl_cffi import requests as cr
except ImportError:
    print("curl: n/a")
else:
    try:
        cr.get("https://example.com", timeout=3); print("curl: OPEN")
    except Exception as e:
        print("curl: blocked" if "забранен" in str(e) else f"curl: other {type(e).__name__}: {e}")
'''

print("── 1. под защитата (PYTHONPATH=tests/_nonet): socket и curl_cffi ──")
env = {k: v for k, v in os.environ.items() if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
env["PYTHONPATH"] = str(ROOT / "tests" / "_nonet")
out = subprocess.run([sys.executable, "-c", PROBE], env=env, capture_output=True, text=True, timeout=60).stdout.split()
got = dict(zip(out[0::2], out[1::2]))
assert got.get("socket:") == "blocked", out
assert got.get("curl:") in ("blocked", "n/a"), out
print(f"  ✓ socket — спрян; curl_cffi (yfinance) — {'спрян' if got.get('curl:') == 'blocked' else 'не е инсталиран'}")

print("── 2. 23.11.2026: пуснат директно (без PYTHONPATH) — модулът nonet_guard спира мрежата и маха тайните ──")
env2 = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",) and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
env2["ANTHROPIC_API_KEY"] = "sk-синтетичен"                                                           # СИНТЕТИЧНО: ключ в средата
probe2 = ("import sys; sys.path.insert(0, %r); import nonet_guard, os; print('key:', 'present' if os.environ.get('ANTHROPIC_API_KEY') else 'removed')\n" % str(ROOT / "tests" / "_nonet")) + PROBE
out2 = subprocess.run([sys.executable, "-c", probe2], env=env2, capture_output=True, text=True, timeout=60).stdout.split()
got2 = dict(zip(out2[0::2], out2[1::2]))
assert got2.get("key:") == "removed" and got2.get("socket:") == "blocked" and got2.get("curl:") in ("blocked", "n/a"), out2
print("  ✓ ключът — махнат; socket и curl_cffi — спрени")

print("── 3. всеки test_*.py внася nonet_guard ПРЕДИ config и src ──")
import ast
missing, late = [], []
for f in sorted(ROOT.glob("test_*.py")):
    tree = ast.parse(f.read_text(encoding="utf-8"))
    names = []
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.Import):
            names += [(i, a.name) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append((i, node.module or ""))
    g = [i for i, n in names if n == "nonet_guard"]
    first = [i for i, n in names if n == "config" or n == "src" or n.startswith("src.")]
    if not g:
        missing.append(f.name)
    elif first and g[0] > min(first):
        late.append(f.name)
assert not missing and not late, (missing[:10], late[:10])
print(f"  ✓ {len(list(ROOT.glob('test_*.py')))} теста — модулът е първи")

print("── 4. test_qm_render.py, пуснат директно — без заявка към EDGAR (23.11: 403 от data.sec.gov) ──")
r = subprocess.run([sys.executable, str(ROOT / "test_qm_render.py")], env={k: v for k, v in env2.items() if k != "ANTHROPIC_API_KEY"}, cwd=str(ROOT), capture_output=True, text=True, timeout=300)
assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
assert "data.sec.gov" not in r.stdout + r.stderr and "HTTPError" not in r.stdout + r.stderr and "забранен" in r.stdout + r.stderr, (r.stdout + r.stderr)[-1500:]
print("  ✓ мина; опитът за EDGAR — спрян от модула („тест към мрежата е забранен“), не HTTPError")
print("\n✅ test_nonet_guard: всичко мина")
