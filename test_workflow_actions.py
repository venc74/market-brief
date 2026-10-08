"""
.github/workflows · версиите на GitHub actions без Node 20 (09.10.2026). Анотациите на Tests run-а от 08.10 предупреждаваха: "Node.js 20 is deprecated … actions/checkout@v4, actions/setup-python@v5". Сега:
actions/checkout@v5 и actions/setup-python@v6 (node24) във ВСИЧКИ три workflow-а (tests, daily_brief, oi_snapshot). Само редовете `uses:` са сменени — тригерите не са пипани (daily_brief няма schedule: нарочно,
oi_snapshot е със schedule:).

РЕАЛНО: tests/fixtures/actions_runtime_2026-10-08.json — runs.using от action.yml на всяка основна версия, прочетено на 08.10. Нова основна версия трябва първо да се добави там (след проверка на action.yml).
Пускане: python test_workflow_actions.py
"""
import sys, re, json, pathlib
ROOT = pathlib.Path(__file__).parent
RT = json.loads((ROOT / "tests" / "fixtures" / "actions_runtime_2026-10-08.json").read_text(encoding="utf-8"))["runtime"]
assert RT["actions/checkout@v4"] == "node20" and RT["actions/checkout@v5"] == "node24" and RT["actions/setup-python@v5"] == "node20" and RT["actions/setup-python@v6"] == "node24"

wf = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
assert [p.name for p in wf] == ["daily_brief.yml", "oi_snapshot.yml", "tests.yml"], [p.name for p in wf]
print("── версиите на actions в трите workflow-а ──")
seen = {}
for p in wf:
    text = p.read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*([\w./-]+@[\w.]+)", text, re.M)
    assert uses, p.name
    for u in uses:
        assert u in RT, f"{p.name}: {u} — непозната версия; прочети action.yml и я добави във fixture-а"
        assert RT[u] != "node20", f"{p.name}: {u} още е на node20"
        seen.setdefault(p.name, []).append(u)
assert all(v == ["actions/checkout@v5", "actions/setup-python@v6"] for v in seen.values()), seen
print("  ✓ " + "; ".join(f"{n}: {', '.join(v)}" for n, v in seen.items()) + " — всичките на node24")

print("── тригерите не са пипани ──")
t = {p.name: "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")) for p in wf}          # без коментарите ("Без schedule: нарочно")
has = lambda name, key: re.search(rf"^\s*{key}:", t[name], re.M) is not None
assert not has("daily_brief.yml", "schedule") and has("daily_brief.yml", "workflow_dispatch")                 # нарочно: само външен тригер (cron-job.org)
assert has("oi_snapshot.yml", "schedule") and has("oi_snapshot.yml", "workflow_dispatch")
assert not has("tests.yml", "schedule") and 'branches: ["**"]' in t["tests.yml"]
print("  ✓ daily_brief.yml — без schedule: (workflow_dispatch от cron-job.org); oi_snapshot.yml — със schedule:; tests.yml — при push")
print("\n✅ test_workflow_actions: всичко мина")
