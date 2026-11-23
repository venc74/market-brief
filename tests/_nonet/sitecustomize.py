"""
Защита на тестовете от мрежа: зарежда се автоматично във всеки тестов процес чрез PYTHONPATH (run_tests.py). От 23.11.2026 логиката е в nonet_guard.py — внася я и всеки
test_*.py в първия си ред, за да важи и при „python test_x.py“.
"""
import nonet_guard  # noqa: F401
