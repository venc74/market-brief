"""
Защита на тестовете от мрежа (пакет 4а т.10): зарежда се автоматично във всеки тестов процес чрез PYTHONPATH
(виж run_tests.py). Всяка опит за връзка към адрес извън loopback гърми веднага — тест, който вика платено API
(Claude), Yahoo, SEC и т.н., се проваля шумно, вместо тихо да харчи пари или да зависи от интернет.
"""
import os
import socket

# втори преглед (10.10.2026): прокси на loopback заобикаляше проверката по адрес (връзката е към 127.0.0.1, проксито тунелира навън) — махат се и тук,
# за тест, пуснат директно (python test_x.py) в среда с прокси; run_tests.clean_env ги маха също
for _k in [k for k in os.environ if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "ftp_proxy")]:
    os.environ.pop(_k, None)

_LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _is_local(address) -> bool:
    if isinstance(address, (str, bytes)):                       # unix socket
        return True
    return str(address[0]) in _LOCAL


_real_connect, _real_connect_ex, _real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo


def _connect(self, address):
    if not _is_local(address):
        raise RuntimeError(f"тест към мрежата е забранен (опит за връзка към {address[0]!r})")
    return _real_connect(self, address)


def _connect_ex(self, address):
    if not _is_local(address):
        raise RuntimeError(f"тест към мрежата е забранен (опит за връзка към {address[0]!r})")
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *a, **k):
    if str(host) not in _LOCAL:
        raise RuntimeError(f"тест към мрежата е забранен (DNS за {host!r})")
    return _real_getaddrinfo(host, *a, **k)


socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = _connect, _connect_ex, _getaddrinfo


# 20.10.2026 (етап 3): yfinance (≥ 0.2.5x) тегли през curl_cffi — libcurl отваря сокетите си в C и заобикаля проверката по-горе. Проверено на 20.10: под тази защита
# socket.create_connection('finance.yahoo.com') беше спрян, а yf.Ticker('SPY').history(period='5d') върна 5 живи бара. Затова и Curl.perform гърми — при първия импорт на
# curl_cffi.curl (без да се импортира тук във всеки тестов процес).
import importlib.abc
import importlib.machinery
import sys


def _no_curl(self, *a, **k):
    raise RuntimeError("тест към мрежата е забранен (curl_cffi — тегленето на yfinance)")


class _CurlGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name != "curl_cffi.curl":
            return None
        spec = importlib.machinery.PathFinder.find_spec(name, path)
        if spec is None or spec.loader is None:
            return spec
        exec_module = spec.loader.exec_module

        def _exec(module):
            exec_module(module)
            module.Curl.perform = _no_curl
        spec.loader.exec_module = _exec
        return spec


sys.meta_path.insert(0, _CurlGuard())


# 20.10.2026 (етап 3б, т. 4): тест, който ЧЕТЕ реалните данни — data/ или публикуваните брифове в docs/data/ — е провал. run_tests.py дава MB_GUARD_ROOT (коренът на репото) и
# MB_TEST_READ_LOG (файл във временната папка на теста); всяко отваряне на файл под двете папки се записва там и run_tests маркира теста FAIL. Изключение тук не се вдига:
# graceful кодът би го погълнал и тестът би минал тихо. Записът го пази отпечатъкът на run_tests. Одит на 20.10: 25 теста четяха docs/data/ (речника), 7 — data/.
_READ_LOG, _GUARD_ROOT = os.environ.get("MB_TEST_READ_LOG"), os.environ.get("MB_GUARD_ROOT")
if _READ_LOG and _GUARD_ROOT:
    _GUARDED = tuple(os.path.join(os.path.realpath(_GUARD_ROOT), d) + os.sep for d in ("data", os.path.join("docs", "data")))

    def _read_hook(event, args):
        if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        try:
            p = os.path.realpath(os.fsdecode(args[0]))
        except Exception:
            return
        if p.startswith(_GUARDED):
            with open(_READ_LOG, "a", encoding="utf-8") as f:              # логът е извън защитените папки — не се записва сам
                f.write(p + "\n")

    sys.addaudithook(_read_hook)
