"""
Защита на тестовете от мрежа (пакет 4а т.10): зарежда се автоматично във всеки тестов процес чрез PYTHONPATH
(виж run_tests.py). Всяка опит за връзка към адрес извън loopback гърми веднага — тест, който вика платено API
(Claude), Yahoo, SEC и т.н., се проваля шумно, вместо тихо да харчи пари или да зависи от интернет.
"""
import socket

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
