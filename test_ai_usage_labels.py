"""
ai_usage · всяко AI извикване има четим етикет, не "<lambda>" (09.10.2026). ai_brief._call_claude етикетира секцията по името на извикващата функция; извикването за катализатора на EP беше lambda и в брифа от 09.10
излезе като секция "<lambda>". Сега е именуваната qm_ep.ep_catalyst_call с етикет "EP катализатор".

РЕАЛНО: заглавията на SYNA от 02.10.2026 (tests/fixtures/qm_ep_2026-10-02.json) и РЕАЛНИТЕ секции на ai_usage от брифа на 09.10 (tests/fixtures/ai_usage_2026-10-09.json — полето ai_usage на брифа). СИНТЕТИЧНО (маркирано): подменената HTTP заявка към
Anthropic (отговорът и токените са измислени) — проверява се само етикетът.
Пускане: python test_ai_usage_labels.py
"""
import sys, json, pathlib, ast, io, contextlib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

import config
from src import ai_brief, qm_ep

F = json.loads((ROOT / "tests" / "fixtures" / "qm_ep_2026-10-02.json").read_text(encoding="utf-8"))
REAL_USAGE = json.loads((ROOT / "tests" / "fixtures" / "ai_usage_2026-10-09.json").read_text(encoding="utf-8"))

print("── 1. РЕАЛНИЯТ ai_usage от 09.10: къде беше проблемът ──")
secs = [u["section"] for u in REAL_USAGE]
assert "<lambda>" in secs and secs.count("<lambda>") == 1
print(f"  ✓ секциите на 09.10: {sorted(set(secs))} — единствената лоша е «<lambda>» (токени: {next(u for u in REAL_USAGE if u['section'] == '<lambda>')['output_tokens']} изход)")

print()
print("── 2. пътят през classify_catalysts с реалните заглавия на SYNA (СИНТЕТИЧЕН отговор на модела) ──")
class FakeResp:
    status_code = 200
    def raise_for_status(self): pass
    def json(self):
        return {"content": [{"type": "text", "text": json.dumps({"items": [{"ticker": "SYNA", "catalyst": "unknown", "summary_bg": None, "surprise": "unclear"}]})}],
                "usage": {"input_tokens": 321, "output_tokens": 45}, "stop_reason": "end_turn"}
ai_brief.requests.post = lambda *a, **kw: FakeResp()
config.ANTHROPIC_API_KEY = "test-key-not-real"
ai_brief.AI_USAGE.clear()
rows = [{"ticker": "SYNA", "headlines": F["headlines"]["SYNA"]}]
with contextlib.redirect_stdout(io.StringIO()):
    res, notes = qm_ep.classify_catalysts(rows)
assert [u["section"] for u in ai_brief.AI_USAGE] == ["EP катализатор"], ai_brief.AI_USAGE
assert ai_brief.AI_USAGE[0]["max_tokens"] == 1500 and ai_brief.AI_USAGE[0]["output_tokens"] == 45
print(f"  ✓ ai_usage: секция «{ai_brief.AI_USAGE[0]['section']}» (max_tokens 1500, 45 изходни токена) — не «<lambda>»")

print()
print("── 3. всяко място в кода, което вика _call_claude, има етикет ──")
bad, seen = [], []
for path in sorted((ROOT / "src").glob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parents[ch] = node
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Attribute) and node.func.attr == "_call_claude") or (isinstance(node.func, ast.Name) and node.func.id == "_call_claude")):
            p = parents.get(node)
            while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                p = parents.get(p)
            name = "<lambda>" if isinstance(p, ast.Lambda) else (p.name if p is not None else "<module>")
            seen.append((path.name, name))
            if name not in ai_brief._SECTION_LABELS:
                bad.append((path.name, name))
assert not bad, bad
assert ("qm_ep.py", "ep_catalyst_call") in seen and not any(n == "<lambda>" for _, n in seen)
print(f"  ✓ {len(seen)} извиквания в {len({f for f, _ in seen})} файла: всяко е във функция с етикет в _SECTION_LABELS, нито едно в lambda ({sorted({n for _, n in seen})})")
print("\n✅ test_ai_usage_labels: всичко мина")
