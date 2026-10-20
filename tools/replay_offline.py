"""
Офлайн реплей (етап 3, част Б): стар ↔ нов код върху снимките на последните N реални брифа — без мрежа, нищо в истинските docs/ и data/.

  python tools/replay_offline.py --base REF [--days 24] [--work DIR]

  • "стар" код = git archive REF (src/, templates/, config.py); "нов" = работното дърво.
  • за всеки от последните N бот commit-а "brief: YYYY-MM-DD" — data/ от този commit (снимката, с която е излязъл брифът) във временна папка; събирачът
    (tools/replay_collect.py) се пуска в отделен процес с копие на кода и снимката, мрежата е блокирана (tests/_nonet), секретите са махнати от средата;
  • сравнява изхода (страница, имейл, книги, четци, сесии, сетъпи; веднъж — сесиите за 2024–2028 и ADR върху реалните барове от fixture-ите) и печата разликите.
Изходът: WORK/report.json и обобщение на екрана. Код 0 — без разлики; 1 — има разлики (всяка трябва да е обяснена).
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile, time

REPO = pathlib.Path(__file__).resolve().parent.parent
CODE = ("src", "templates", "config.py")
SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "EDGAR_UA", "GMAIL", "EMAIL_TO", "PROXY")


def git(*a, **k) -> str:
    return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, check=True, **k).stdout


def bot_dates(base: str, n: int) -> list[tuple[str, str]]:
    rows = [l.split(" ", 2) for l in git("log", "--author=brief-bot", "--format=%h %s", base).splitlines()]
    out = [(h, s.split(": ", 1)[1]) for h, s in ((r[0], r[1] + " " + r[2]) for r in rows if len(r) == 3) if s.startswith("brief: ")]
    return out[:n][::-1]


def extract(ref: str, paths, dest: pathlib.Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    p1 = subprocess.Popen(["git", "-C", str(REPO), "archive", ref, *paths], stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", str(dest)], stdin=p1.stdout, check=True)
    p1.wait()


def code_tree(side: str, base: str, dest: pathlib.Path) -> None:
    if side == "old":
        extract(base, CODE, dest)
    else:
        for c in CODE:
            src = REPO / c
            (shutil.copytree(src, dest / c, ignore=shutil.ignore_patterns("__pycache__")) if src.is_dir() else shutil.copy2(src, dest / c))
    shutil.copy2(REPO / "tools" / "replay_collect.py", dest / "replay_collect.py")


def env() -> dict:
    e = {k: v for k, v in os.environ.items() if not any(h in k.upper() for h in SECRET_HINTS)}
    e["PYTHONPATH"] = str(REPO / "tests" / "_nonet")
    return e


def run(cmd, cwd) -> None:
    r = subprocess.run(cmd, cwd=cwd, env=env(), capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))}\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")


def diff(a, b, path="", out=None, cap=2000):
    out = [] if out is None else out
    if len(out) >= cap:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append((f"{path}.{k}", a.get(k, "<няма>"), b.get(k, "<няма>")))
            else:
                diff(a[k], b[k], f"{path}.{k}", out, cap)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out, cap)
    elif a != b:
        out.append((path, a, b))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--days", type=int, default=24)
    ap.add_argument("--work", default=None)
    args = ap.parse_args()
    work = pathlib.Path(args.work or tempfile.mkdtemp(prefix="mb_replay_"))
    work.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    t0 = time.time()
    days = bot_dates(args.base, args.days)
    print(f"[replay] {len(days)} брифа: {days[0][1]} … {days[-1][1]}; стар код = {args.base}, нов = работното дърво; папка {work}")
    report = {"base": args.base, "days": [d for _, d in days], "diffs": {}}
    for side in ("old", "new"):
        code = work / side / "_code"
        if code.exists():
            shutil.rmtree(code)
        code_tree(side, args.base, code)
    for h, d in days:
        snap = work / "snap" / d
        if not snap.exists():
            extract(h, ["data"], snap)
        for side in ("old", "new"):
            rd = work / side / d
            if rd.exists():
                shutil.rmtree(rd)
            shutil.copytree(work / side / "_code", rd)
            shutil.copytree(snap / "data", rd / "data")
            run([py, str(rd / "replay_collect.py"), "day", d, str(work / side / f"{d}.json")], rd)
            shutil.rmtree(rd)
        a = json.loads((work / "old" / f"{d}.json").read_text(encoding="utf-8"))
        b = json.loads((work / "new" / f"{d}.json").read_text(encoding="utf-8"))
        dd = diff(a, b)
        report["diffs"][d] = dd
        print(f"[replay] {d}: {'= същото' if not dd else f'≠ {len(dd)} разлики'}")
    for side in ("old", "new"):
        run([py, str(work / side / "_code" / "replay_collect.py"), "global", str(REPO / "tests" / "fixtures"), str(work / side / "global.json")], work / side / "_code")
    g = diff(json.loads((work / "old" / "global.json").read_text(encoding="utf-8")), json.loads((work / "new" / "global.json").read_text(encoding="utf-8")))
    report["diffs"]["global"] = g
    print(f"[replay] сесии 2024–2028 и ADR върху fixture-ите: {'= същото' if not g else f'≠ {len(g)} разлики'}")
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, default=str, indent=1), encoding="utf-8")
    total = sum(len(v) for v in report["diffs"].values())
    for k, v in report["diffs"].items():
        for p, x, y in v[:5]:
            print(f"   {k} {p}: {str(x)[:140]!r} → {str(y)[:140]!r}")
    print(f"[replay] общо разлики: {total} · {time.time() - t0:.0f}s · {work / 'report.json'}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
