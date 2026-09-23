"""
model_selector.py — избира кой Claude модел ползва дневният бриф.

Преди: `config.CLAUDE_MODEL` беше фиксиран низ, който трябваше да се сменя на
ръка при всеки нов модел. Сега pipeline-ът пита Models API-то кои модели са
налични и взима най-новия sonnet.

Три защити, в този ред:

1. ЕСКЕЙП ХАЧ. Ако `CLAUDE_MODEL` е ИЗРИЧНО зададена в средата, тя печели и
   discovery изобщо не се пуска. Така при проблем с нов модел се закотвя с една
   променлива в workflow-а — без code промяна и без да се чака нов push.

2. PROBE. Успешно свален списък НЕ значи работещ модел: Sonnet 5 например връща
   400 за `budget_tokens`, а бъдещ модел може да отхвърли параметър, който
   `_call_claude` изпраща, или да смени поведение по подразбиране. Тогава
   discovery-то е успяло, а всяка AI стъпка би паднала една по една. Затова
   изборът се проверява с едно евтино реално извикване ПРЕЗ САМИЯ
   `ai_brief._call_claude` — не през паралелна имплементация. Така параметрите
   са идентични по конструкция и не могат да се разминат при бъдещи промени.

3. FALLBACK. Провал навсякъде (мрежа, празен списък, паднал probe) → връщаме се
   на config.CLAUDE_MODEL_FALLBACK, известният работещ модел. Отхвърленият
   модел и причината се носят нагоре и се показват В БРИФА, не само в лога.

Състоянието (кой модел е ползван, кога се е сменил) се пази в
data/model_state.json, за да може брифът да покаже банер при смяна.
"""
from __future__ import annotations
import datetime as dt
import json
import re

import requests

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import config

_STATE_PATH = config.DATA_DIR / "model_state.json"
_MODELS_URL = "https://api.anthropic.com/v1/models"

# Dated snapshot (…-20250929) — конкретна замразена версия, не текущият модел.
_SNAPSHOT_RE = re.compile(r"-\d{8}$")
# Служебни/нестабилни варианти, които не искаме да хванем като "най-нов".
_EXCLUDE_TOKENS = ("preview", "experimental", "latest", "deprecated")


def _list_models(timeout: int = 30) -> list[dict]:
    """Всички модели от /v1/models, с пагинация. Провал → изключение нагоре."""
    out: list[dict] = []
    after: str | None = None
    for _ in range(10):  # таван срещу безкраен цикъл при счупена пагинация
        params = {"limit": 100}
        if after:
            params["after_id"] = after
        r = requests.get(_MODELS_URL, headers={
            "x-api-key": config.ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        }, params=params, timeout=timeout)
        r.raise_for_status()
        body = r.json() or {}
        out += body.get("data") or []
        if not body.get("has_more"):
            break
        after = body.get("last_id")
        if not after:
            break
    return out


def pick_newest(models: list[dict], needle: str = "sonnet") -> str | None:
    """
    Най-новият модел, чийто id съдържа `needle`.

    Служебните варианти (preview/experimental/latest/deprecated) отпадат
    безусловно — те не са "текущият" модел, независимо от датата.

    Датираните id-та (…-20250929) се третират ПО-ВНИМАТЕЛНО, а не безусловно
    изключени. Датиран id отпада САМО ако в същия каталог съществува и
    недатираният му еквивалент — тогава той е просто замразено копие на същата
    версия и недатираният е правилният избор. Ако версията съществува ЕДИНСТВЕНО
    в датиран вид, тя остава кандидат.

    Причината за тази разлика: безусловното изключване има тих режим на провал.
    Ако бъдещ Sonnet излезе само като датиран id (както claude-haiku-4-5-20251001
    в момента), филтърът би го прескочил, би избрал по-стар Sonnet, probe-ът би
    минал и банер нямаше да има — брифът никога не се обновява, без нито един
    видим сигнал. Точно класът дефект, който тази система е построена да лови.

    Подредбата е по created_at низходящо, с id като вторичен ключ — само за
    детерминизъм при еднакви дати, не като смислов критерий.
    """
    known = {(m.get("id") or "").strip().lower() for m in models}
    cands = []
    for m in models:
        mid = (m.get("id") or "").strip()
        low = mid.lower()
        if needle not in low:
            continue
        if any(t in low for t in _EXCLUDE_TOKENS):
            continue
        snap = _SNAPSHOT_RE.search(low)
        if snap and low[:snap.start()] in known:
            continue  # има недатиран еквивалент → този е замразено копие
        cands.append((m.get("created_at") or "", mid))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]


def _probe(model: str) -> tuple[bool, str]:
    """
    Едно реално извикване през ai_brief._call_claude със същите параметри като
    истинските стъпки. Връща (успех, причина при провал).

    Извиква се САМИЯТ _call_claude, не копие на заявката — иначе probe-ът и
    реалните стъпки биха се разминали при бъдеща промяна в единия.
    """
    from src import ai_brief
    saved = config.CLAUDE_MODEL
    config.CLAUDE_MODEL = model
    try:
        # allow_truncation: probe-ът проверява дали моделът ОТГОВАРЯ, не дали
        # отговорът се побира — отрязан отговор на 16 токена е успех тук, и не
        # бива да се записва като предупреждение в брифа.
        ai_brief._call_claude("Отговаряй с една дума.", "Кажи: ок",
                              max_tokens=config.MODEL_PROBE_MAX_TOKENS,
                              allow_truncation=True)
        return True, ""
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"
        resp = getattr(e, "response", None)
        if resp is not None:
            body = (getattr(resp, "text", "") or "")[:200]
            detail = f"HTTP {getattr(resp, 'status_code', '?')} — {body}"
        return False, detail
    finally:
        config.CLAUDE_MODEL = saved


def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[model] model_state.json нечетим, започвам от празно: {e}")
    return {}


def _save_state(state: dict) -> None:
    try:
        config.DATA_DIR.mkdir(exist_ok=True)
        _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1,
                                          default=str), encoding="utf-8")
    except Exception as e:
        print(f"[model] state write: {e}")


def _update_state(model: str, today: str) -> dict:
    """
    Проследява смените и връща банер информацията.

    Банерът стои config.MODEL_BANNER_RUNS ПОСЛЕДОВАТЕЛНИ run-а след смяна, с
    брояч в текста. Броячът НЕ мърда при повторен run в същия ден (ръчен
    re-trigger) — иначе един ден би изял два от петте.

    Първият run изобщо (празно състояние) не е "смяна" — няма от какво да се е
    сменило, банер не се показва.
    """
    state = _load_state()
    prev = state.get("previous_model")
    runs = state.get("runs_since_change") or 0
    changed_on = state.get("changed_on")

    # FIX 2026-09-23: липсващ запис НЕ значи "няма предишен модел". Преди
    # model_state.json да съществува, брифът е работил на
    # CLAUDE_MODEL_FALLBACK — това е факт, не предположение. Старото условие
    # (`state.get("model") and ...`) приемаше празния файл за "няма смяна" и
    # на 23.09 премълча точно първата смяна към claude-sonnet-5 — същият клас
    # тих провал като безусловното изключване на датираните id-та.
    known = state.get("model") or config.CLAUDE_MODEL_FALLBACK
    if known != model:
        prev, runs, changed_on = known, 1, today
    elif runs and state.get("last_run_date") != today:
        runs += 1
    if runs > config.MODEL_BANNER_RUNS:
        runs, prev, changed_on = 0, None, None

    _save_state({"model": model, "previous_model": prev, "changed_on": changed_on,
                 "runs_since_change": runs, "last_run_date": today})
    if runs and prev:
        return {"changed": True, "from": prev, "to": model,
                "day": runs, "of": config.MODEL_BANNER_RUNS}
    return {}


def resolve_model(today: str | None = None) -> dict:
    """
    Точката на влизане. Извиква се ВЕДНЪЖ в началото на pipeline-а; резултатът
    се присвоява на config.CLAUDE_MODEL и всички AI стъпки го наследяват, защото
    _call_claude чете config.CLAUDE_MODEL при всяко извикване.

    Връща {model, source, rejected, rejected_reason, banner} — `rejected` се
    показва в брифа, не само се логва.
    """
    today = today or dt.date.today().isoformat()
    fallback = config.CLAUDE_MODEL_FALLBACK

    # FIX 2026-09-23 (политика): смяна на модел САМО с изрична команда.
    # Изрично зададеният CLAUDE_MODEL вече НЕ прескача probe-а и банера — те
    # са точно толкова полезни при ръчна смяна, колкото при автоматична.
    chosen, rejected, reason, source = None, None, "", "auto"
    if config.CLAUDE_MODEL_PINNED:
        chosen, source = config.CLAUDE_MODEL, "env"
        print(f"[model] CLAUDE_MODEL е изрично зададен ({chosen}) — discovery пропуснато")
    elif not config.MODEL_AUTO_SELECT:
        chosen, source = fallback, "disabled"
        print(f"[model] автоматичният избор е изключен — {fallback}")
    else:
        try:
            models = _list_models()
            chosen = pick_newest(models)
            if chosen:
                print(f"[model] от {len(models)} модела избран най-нов sonnet: {chosen}")
            else:
                reason = f"списъкът върна {len(models)} модела, нито един подходящ sonnet"
                print(f"[model] {reason}")
        except Exception as e:
            reason = f"Models API недостъпен ({type(e).__name__}: {e})"
            print(f"[model] {reason}")

    if chosen and chosen != fallback:
        ok, why = _probe(chosen)
        if not ok:
            rejected, reason = chosen, why
            print(f"[model] ⚠ probe за {chosen} падна — {why}")
            chosen = None
        else:
            print(f"[model] probe за {chosen} мина")

    model = chosen or fallback
    if model == fallback and chosen is None:
        print(f"[model] връщам се на резервния {fallback}")
    print(f"[model] дневният бриф ползва: {model}")
    return {"model": model, "source": source if chosen else "fallback",
            "rejected": rejected, "rejected_reason": reason,
            "banner": _update_state(model, today)}
