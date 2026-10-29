"""
29.10.2026 · разходката, т. 5 (макро бриф), решения 1–4:
  1. абзацът на AI за режима (regime_comment) е махнат — режимът е горе, в термометъра, от кода; махнати са и проверките, които бяха само за него (regime_claims.clean върху
     макро текста: броене, правило, distribution days, кредитен стрес) и бележките в промпта (броенето, правилото, exit_rule, „Запас до смяна на режима“, блокът от distribution
     days, освободеният override). Общите остават: отрязване + повторен опит, чужди символи, изтеклите клаузи-проверки (strip_meta), секторните твърдения;
  2. "macro_brief" е разказ в 2–3 кратки абзаца (празен ред между тях) от подадените входове — новините, крипто секцията, глобалните сигнали и уредите на термометъра като
     контекст, без броене и без думата „режим“; последното изречение — „За нас: …“ за водещите сектори;
  3. социалните мрежи — само когато секцията я има (пакетът след разходката), само при ясен случай;
  4. редът за фючърсите (код) остава под разказа.
Крипто секцията се строи ПРЕДИ макро брифа (main.py), за да я вижда разказът; COT за Bitcoin се добавя след COT модула.

РЕАЛНО: tests/fixtures/macro_story_2026-10-29.json — входовете на макро брифа от 29.10 (macro, rotation, thermometer, news, crypto) и публикуваните текстове;
tests/fixtures/brief_2026-10-19.json — брифът за страницата (с РЕАЛЕН regime_comment от 19.10 — вече не се показва).
СИНТЕТИЧНО (означено): отговорът на модела (разказът в т. 2), секцията за социалните мрежи в т. 4 (още я няма), подмененият _call_claude.
Пускане: python test_macro_story.py
"""
import sys, json, copy, pathlib, tempfile, io, contextlib, re, html as htmllib
ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
_tmp = tempfile.TemporaryDirectory(prefix="mb_story2_")
config.DATA_DIR = pathlib.Path(_tmp.name) / "data"; config.DOCS_DIR = pathlib.Path(_tmp.name) / "docs"
config.DATA_DIR.mkdir(); config.DOCS_DIR.mkdir()
from src import ai_brief, render

FX = json.loads((ROOT / "tests" / "fixtures" / "macro_story_2026-10-29.json").read_text(encoding="utf-8"))
B19 = json.loads((ROOT / "tests" / "fixtures" / "brief_2026-10-19.json").read_text(encoding="utf-8"))
q = lambda: contextlib.redirect_stdout(io.StringIO())

print("── 1. промптът върху РЕАЛНИТЕ входове от 29.10 ──")
p = ai_brief.macro_user_prompt(FX["macro"], FX["rotation"], FX["thermometer"], FX["news"], FX["crypto"])
assert ai_brief.NARRATIVE_RULES in p and "„За нас:“" in p and "2 или 3 кратки абзаца" in p and "без думата „режим“" in p
assert "ВОДЕЩИТЕ НИ СЕКТОРИ (по кода): Енергетика (XLE), Здравеопазване (XLV)" in p
assert "Bitcoin ETF inflows climb to $176M as BTC rebounds above $80K" in p and '"ticker": "HOOD", "chg_1d_pct": -3.3' in p              # крипто секцията (т. 4)
assert "Alphabet sinks 10% as it holds 2026 capex unchanged" in p                                                                        # новините (т. 3)
for gone in ("regime_comment", "exit_rule", "regime_margin", "ЗАПАС ДО СМЯНА НА РЕЖИМА", "НЕ преброявай", "overrides", "regime_by_count", '"regime":', "distribution_cap"):
    assert gone not in p, gone
ctx = p[p.index("УРЕДИТЕ НА ТЕРМОМЕТЪРА"):p.index("МАКРО (FRED")]
assert '"name": "VIX", "value": 16.91, "label": "VIX 16.9 (risk-on)"' in ctx and '"status"' not in ctx                                # уредите — като контекст, без цветовете
assert "СОЦИАЛНИ МРЕЖИ" not in p and "излиза с ~6 седмици закъснение" in p
print(f"  ✓ {len(p)} знака: правилата за разказа, водещите сектори, крипто, новините, уредите без цвят; без режима, броенето, правилото и запаса")

print()
print("── 2. отговорът: разказ в 3 абзаца → страницата (3 <p>), имейлът (<br><br>); regime_comment не се показва (СИНТЕТИЧЕН разказ) ──")
story = ("Нощта мина под знака на два отчета, които показаха едно и също нещо от две страни.\n\n"
         "Fed не пипна лихвите, но пазарът чу напомняне, че инфлацията още не е победена.\n\n"
         "За нас: денят е за енергетика и здравеопазване, а технологиите са под натиск.")                                              # СИНТЕТИЧНО
ai_brief._call_claude = lambda system, user, **k: json.dumps({"macro_brief": story, "sector_logic": []}, ensure_ascii=False)
with q():
    out = ai_brief.macro_and_sector_brief(FX["macro"], FX["rotation"], FX["thermometer"], news=FX["news"], crypto=FX["crypto"])
assert out["macro_brief"] == story and "regime_comment" not in out and ai_brief.paragraphs(out["macro_brief"])[2].startswith("За нас:")
b = copy.deepcopy(B19); b["ai_macro"] = {**b["ai_macro"], "macro_brief": story}
assert b["ai_macro"].get("regime_comment")                                                                                               # РЕАЛНИЯТ regime_comment от 19.10 — в данните
with q():
    page = render.render_dashboard(b, publish=False)
    mail = render.render_email(b)
sec = page[page.index("<h2>Макро бриф</h2>"):]; sec = sec[:sec.index("</section>")]
assert sec.count('<p style="margin:0') == 3 and b["ai_macro"]["regime_comment"][:40] not in page and b["ai_macro"]["regime_comment"][:40] not in mail
assert "две страни.<br><br>Fed не пипна" in htmllib.unescape(mail)
if render._futures_line(b):
    assert sec.index("За нас:") < sec.index(htmllib.escape(render._futures_line(b))[:30])                                             # фючърсите — под разказа
print("  ✓ 3 абзаца на страницата, <br><br> в имейла; РЕАЛНИЯТ regime_comment от 19.10 не се показва; фючърсите остават под разказа")

print()
print("── 3. общите проверки по абзаци — абзаците не се сливат (РЕАЛНА клауза-проверка от 28.10 като втори абзац) ──")
meta = "Никоя от наличните стойности не е null/nan."                                                                                     # РЕАЛНО изречение (regime_comment, 28.10)
ai_brief._call_claude = lambda system, user, **k: json.dumps({"macro_brief": "Първи абзац.\n\nВтори абзац. " + meta + "\n\nЗа нас: енергетика.", "sector_logic": []}, ensure_ascii=False)
with q():
    out = ai_brief.macro_and_sector_brief(FX["macro"], FX["rotation"], FX["thermometer"], news=FX["news"], crypto=FX["crypto"])
assert out["macro_brief"] == "Първи абзац.\n\nВтори абзац.\n\nЗа нас: енергетика." and out["regime_claims_fixed"][0]["code"] == "meta"
print("  ✓ клаузата-проверка пада, трите абзаца остават")

print()
print("── 4. социалните мрежи — само когато секцията я има (СИНТЕТИЧНО) ──")
p2 = ai_brief.macro_user_prompt(FX["macro"], FX["rotation"], FX["thermometer"], FX["news"], FX["crypto"], social={"rising": [{"ticker": "GOOG", "mentions": 610, "mentions_24h_ago": 81}]})
assert ai_brief.SOCIAL_RULE in p2 and "„в социалните мрежи се говори за …“" in p2 and '"mentions": 610' in p2
assert ai_brief._social_block(None) == "" and ai_brief._social_block({}) == ""
print("  ✓ със секцията — правилото и данните; без нея — нищо")
print("\n✅ test_macro_story: всичко мина")
