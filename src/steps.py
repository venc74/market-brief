"""
Обвивка на стъпките в main.run (етап 3б, 20.10.2026 — дизайнът от доклада на етап 3, одобрен). Всяка стъпка казва по един и същ начин ok / частично / провал / пропусната;
провал или частичен резултат има банер. До 20.10 ~45 места try/except в main.run имаха три навика: модулен LAST_STATUS, който data_warnings чете; локален diag речник; само ред
в лога, без банер. Стъпка 1 (тук): обвивката и местата "само лог" — около 15 (отчетите, обратният залог, маркерите върху позициите, обобщенията на книгите …).

  step(name, fn, …) — fn() в try/except, с време; изключение → fallback, статус "failed", ред в лога; partial(value) → (причина, детайл) или None; critical=True — изключението
  се вдига (рендерът и записът — там провалът и днес сваля run-а). Стъпка с enabled=False е "skipped" (изключена в config) — без банер.
  summary() → brief["run_steps"]; warnings(present) → банерите за провалените / частичните стъпки, чийто source още НЯМА банер (стъпка със собствен точен банер не получава втори).
Стъпка 3 (20.10): местата с МОДУЛЕН статус (LAST_STATUS / LAST_DIAG — термометър, сектори, скрийнър, AI наративите, distribution days, GLB, отделяне) — on_fail прави същото като
досега; failed_if(value) / partial(value) четат модулния статус (провал без изключение — празен резултат от паднал Yahoo — също е "failed" в run_steps), банерът е собственият.
Стъпка 2 (20.10): местата с ЛОКАЛЕН статус (qm_diag, статусът на INS✓ за позициите, EP, здравният монитор) — on_fail(exc) връща същия статус като досега, собственият банер остава.
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class StepResult:
    name: str
    status: str                       # "ok" | "partial" | "failed" | "skipped"
    label: str = ""
    consequence: str = ""
    source: str = ""
    reason: str | None = None
    error_type: str | None = None
    detail: dict = field(default_factory=dict)
    seconds: float = 0.0


RUN: list[StepResult] = []


def reset() -> None:
    """Нов run."""
    RUN.clear()


def step(name: str, fn: Callable[[], Any], *, fallback: Any = None, label: str, consequence: str, source: str | None = None,
         partial: Callable[[Any], tuple[str, dict] | None] | None = None, critical: bool = False, enabled: bool = True, trace: bool = False,
         on_fail: Callable[[Exception], Any] | None = None, failed_if: Callable[[Any], str | None] | None = None) -> Any:
    """Изпълнява fn() и записва резултата в RUN; връща стойността (или fallback при провал / пропусната стъпка; при провал с on_fail — on_fail(exc))."""
    res = StepResult(name=name, status="ok", label=label, consequence=consequence, source=source or name)
    if not enabled:
        res.status = "skipped"
        RUN.append(res)
        return fallback
    t0 = time.monotonic()
    try:
        value = fn()
    except Exception as e:
        res.seconds = round(time.monotonic() - t0, 1)
        res.status, res.reason, res.error_type = "failed", f"{type(e).__name__}: {e}"[:300], type(e).__name__
        RUN.append(res)
        if trace:
            traceback.print_exc()
        print(f"[step] {name}: ПРОВАЛ — {res.reason} ({label}: {consequence})")
        if critical:
            raise
        return on_fail(e) if on_fail is not None else fallback
    res.seconds = round(time.monotonic() - t0, 1)
    if failed_if is not None:
        try:
            why = failed_if(value)
        except Exception as e:
            why = None
        if why:
            res.status, res.reason = "failed", str(why)[:300]
            print(f"[step] {name}: ПРОВАЛ — {res.reason}")
            RUN.append(res)
            return value
    if partial is not None:
        try:
            p = partial(value)
        except Exception as e:                                       # проверката за частичен резултат не сваля стъпката
            p = (f"проверката за частичен резултат не се изпълни ({type(e).__name__})", {})
        if p:
            res.status, res.reason = "partial", p[0]
            res.detail = dict(p[1] or {})
            print(f"[step] {name}: ЧАСТИЧНО — {res.reason}")
    RUN.append(res)
    return value


def result(name: str) -> StepResult | None:
    """Последният запис на стъпката (None, ако не е изпълнявана)."""
    return next((r for r in reversed(RUN) if r.name == name), None)


def summary() -> list[dict]:
    """brief["run_steps"]: [{name, status, reason, seconds}] в реда на изпълнение."""
    return [{"name": r.name, "status": r.status, "reason": r.reason, "seconds": r.seconds, **({"detail": r.detail} if r.detail else {})} for r in RUN]


def warnings(present_sources: set[str] | None = None, results: list[StepResult] | None = None) -> list[dict]:
    """
    Банерите за стъпките с провал / частичен резултат: "{label}: провал ({reason}) — {consequence}." Стъпка, чийто source вече има банер (собственият точен текст на модула),
    не получава втори. Ниво: провал → error, частично → warn.
    """
    present = set(present_sources or ())
    out, seen = [], set()
    for r in results if results is not None else RUN:
        if r.status not in ("failed", "partial") or r.source in present or r.source in seen:
            continue
        seen.add(r.source)
        what = "провал" if r.status == "failed" else "частично"
        out.append({"source": r.source, "level": "error" if r.status == "failed" else "warn",
                    "message": f"{r.label}: {what} днес ({r.reason}) — {r.consequence}."})
    return out


def log_line() -> str:
    by = {}
    for r in RUN:
        by[r.status] = by.get(r.status, 0) + 1
    bad = [f"{r.name} ({r.status})" for r in RUN if r.status in ("failed", "partial")]
    return (f"[steps] {len(RUN)} стъпки: " + ", ".join(f"{k} {v}" for k, v in sorted(by.items()))
            + (f" — {', '.join(bad)}" if bad else ""))
