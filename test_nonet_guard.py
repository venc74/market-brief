"""
20.10.2026 · етап 3: защитата на тестовете от мрежа (tests/_nonet/sitecustomize.py) спира и curl_cffi. yfinance тегли през curl_cffi (libcurl отваря сокетите в C) и
заобикаляше проверката на socket: на 20.10 под защитата socket.create_connection('finance.yahoo.com') беше спрян, а yf.Ticker('SPY').history(period='5d') върна 5 живи бара.
Два теста са теглили от Yahoo, без да зависят от резултата (test_book_entry_volume — отчетите в обобщението; test_health_monitor — проверката за сплит) — вече подменени.
Преброено с дневник на опитите върху целия набор: 2 опита преди, 0 след.

СИНТЕТИЧНО: заявките към example.com (не излизат — спират се преди мрежата).
Пускане: python test_nonet_guard.py
"""
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
print("\n✅ test_nonet_guard: всичко мина")
