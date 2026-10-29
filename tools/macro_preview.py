"""
29.10.2026 (разходката, т. 5): прегенериране на макро разказа с НОВИЯ промпт върху РЕАЛНИТЕ входове на записан бриф (data/YYYY-MM-DD.json: macro, rotation, thermometer, news,
crypto) — за преглед преди commit. Нищо не се записва в data/ или docs/; изходът е на екрана и (по желание) във файл с --out.

  python tools/macro_preview.py 2026-10-29 --dry-run        # само промптът (без API) — дължина и текст
  ANTHROPIC_API_KEY=… python tools/macro_preview.py 2026-10-29 2026-10-23 --out /tmp/preview.md

Моделът е този от брифа на деня (brief["model_info"]["model"]), освен ако е зададен CLAUDE_MODEL. Ключът се чете от средата — скриптът не го печата.
"""
import sys, os, json, argparse, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config
from src import ai_brief


def inputs(day: str) -> dict:
    b = json.loads((ROOT / "data" / f"{day}.json").read_text(encoding="utf-8"))
    return {"brief": b, "macro": b.get("macro") or {}, "rotation": b.get("rotation") or [], "thermometer": b.get("thermometer") or {},
            "news": b.get("news") or [], "crypto": b.get("crypto") or {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    lines = []
    for day in a.days:
        x = inputs(day)
        prompt = ai_brief.macro_user_prompt(x["macro"], x["rotation"], x["thermometer"], x["news"], x["crypto"])
        if a.dry_run:
            print(f"══ {day}: промптът — {len(prompt)} знака ══\n{prompt}\n")
            continue
        if not config.ANTHROPIC_API_KEY:
            sys.exit("ANTHROPIC_API_KEY липсва в средата")
        if not os.getenv("CLAUDE_MODEL"):
            config.CLAUDE_MODEL = ((x["brief"].get("model_info") or {}).get("model")) or config.CLAUDE_MODEL
        out = ai_brief.macro_and_sector_brief(x["macro"], x["rotation"], x["thermometer"], news=x["news"], crypto=x["crypto"])
        old = (x["brief"].get("ai_macro") or {})
        block = [f"## {day} — нов разказ (модел {config.CLAUDE_MODEL})", "", *[p + "\n" for p in ai_brief.paragraphs(out.get("macro_brief") or "")],
                 f"_Публикуваното на {day} (стария промпт):_", "", (old.get("macro_brief") or "").strip(), "", f"_regime_comment тогава:_ {old.get('regime_comment') or '—'}", "",
                 f"_Проверки:_ {json.dumps({k: out.get(k) for k in ('regime_claims_fixed', 'sector_claims_fixed') if out.get(k)}, ensure_ascii=False)}", ""]
        print("\n".join(block))
        lines += block
    if a.out and lines:
        pathlib.Path(a.out).write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
