#!/usr/bin/env python3
"""
Отрисовка карточек «Факт дня» и «В этот день» в PNG 1080×1080 по разметке холста «Карточки рубрик».

  python tools/render_cards.py week-2026-11-16.json [--handle @da_eto_pravda]

Берёт посты с полем card_data и сохраняет cards/<card>.png (имя = название артборда, поле card).
Проверяет, что текст влезает в карточку: если нет — сообщает и завершается с ошибкой.
Нужен Python-пакет playwright с установленным Chromium.
"""
import argparse
import base64
import html
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FONTS = Path(__file__).resolve().parent / "fonts"
MONTHS = ["ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ", "ИЮЛЬ", "АВГУСТ",
          "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ"]
e = html.escape


def head():
    unb = base64.b64encode((FONTS / "Unbounded.ttf").read_bytes()).decode()
    gol = base64.b64encode((FONTS / "GolosText.ttf").read_bytes()).decode()
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face{{font-family:'Unbounded';src:url(data:font/ttf;base64,{unb}) format('truetype');font-weight:100 900}}
@font-face{{font-family:'Golos Text';src:url(data:font/ttf;base64,{gol}) format('truetype');font-weight:400 900}}
body{{margin:0}}</style></head><body>"""


SEAL = """<div style="position: absolute; top: -110px; right: -70px; width: 250px; height: 250px; transform: rotate(10deg)">
<svg width="250" height="250" viewBox="0 0 400 400"><defs><path id="ring" d="M60,200 a140,140 0 1,1 280,0 a140,140 0 1,1 -280,0"></path></defs>
<circle cx="200" cy="200" r="188" fill="#168A45" stroke="#141414" stroke-width="8"></circle>
<circle cx="200" cy="200" r="114" fill="#FFFFFF" stroke="#141414" stroke-width="6"></circle>
<text font-family="Unbounded, sans-serif" font-weight="800" font-size="34" fill="#FFFFFF"><textPath href="#ring" textLength="862" lengthAdjust="spacing">ДА, ЭТО ПРАВДА • ДА, ЭТО ПРАВДА •</textPath></text>
<path d="M148 204l36 36 70-76" stroke="#168A45" stroke-width="28" stroke-linecap="round" stroke-linejoin="round" fill="none"></path></svg></div>"""

FACT_ICON = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none"><path d="M4 12.5l5 5L20 6.5" stroke="#FFE14D" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"></path></svg>'
DAY_ICON = '<svg width="30" height="30" viewBox="0 0 24 24" fill="none"><rect x="3.5" y="5" width="17" height="15.5" rx="2.5" stroke="#6E9BFF" stroke-width="2.4"></rect><path d="M3.5 10h17M8 3v4M16 3v4" stroke="#6E9BFF" stroke-width="2.4" stroke-linecap="round"></path></svg>'


def frame(hd, ground, icon, label, tag, plate, handle):
    return hd + f"""<div id="card" style="width: 1080px; height: 1080px; box-sizing: border-box; padding: 72px; background: {ground}; font-family: 'Golos Text', sans-serif; color: #141414; display: flex; flex-direction: column; gap: 56px">
<div style="display: flex; justify-content: space-between; align-items: center">
<div style="display: flex; align-items: center; gap: 14px; background: #141414; color: #FFFFFF; border-radius: 999px; padding: 18px 32px 18px 24px; font-family: 'Unbounded', sans-serif; font-weight: 800; font-size: 28px; letter-spacing: 0.05em">{icon}<span>{label}</span></div>
<div style="border: 4px solid #141414; border-radius: 999px; padding: 14px 28px; font-family: 'Unbounded', sans-serif; font-weight: 600; font-size: 24px; background: #FFFFFF; margin-right: 150px">{e(tag)}</div></div>
<div id="plate" style="position: relative; flex-grow: 1; min-height: 0; background: #FFFFFF; border: 6px solid #141414; border-radius: 44px; box-shadow: 14px 14px 0 #141414; margin-right: 14px; {plate[0]}">{plate[1]}{SEAL}</div>
<div style="display: flex; justify-content: space-between; align-items: center">
<div style="font-family: 'Unbounded', sans-serif; font-weight: 800; font-size: 32px">Да, это правда</div>
<div style="font-size: 26px; font-weight: 600">{e(handle)}</div></div></div></body></html>"""


def fact_card(hd, c, handle):
    plate = ("padding: 64px; display: flex; flex-direction: column; justify-content: center; gap: 28px",
             f"""<h1 style="margin: 0; max-width: 640px; font-family: 'Unbounded', sans-serif; font-weight: 800; font-size: 72px; line-height: 1.05; letter-spacing: -0.01em">{e(c['title'])}</h1>
<p style="margin: 0; font-size: 33px; line-height: 1.35; font-weight: 500">{e(c['body'])}</p>""")
    return frame(hd, "#FFE14D", FACT_ICON, "ФАКТ ДНЯ", c["tag"], plate, handle)


def day_card(hd, c, month, handle):
    plate = ("padding: 120px 56px 56px; display: flex; align-items: center; gap: 44px",
             f"""<div style="width: 300px; flex-shrink: 0; background: #FFFFFF; border: 5px solid #141414; border-radius: 28px; overflow: hidden; display: flex; flex-direction: column">
<div style="background: #141414; color: #FFFFFF; font-family: 'Unbounded', sans-serif; font-weight: 800; font-size: 28px; letter-spacing: 0.08em; text-align: center; padding: 20px 0">{month}</div>
<div style="font-family: 'Unbounded', sans-serif; font-weight: 800; font-size: 160px; line-height: 1; text-align: center; padding: 40px 0 14px">{e(str(c['d']))}</div>
<div style="font-family: 'Unbounded', sans-serif; font-weight: 600; font-size: 40px; text-align: center; padding: 0 0 36px">{e(str(c['y']))}</div></div>
<div style="flex-grow: 1; min-width: 0; display: flex; flex-direction: column; gap: 22px">
<h1 style="margin: 0; font-family: 'Unbounded', sans-serif; font-weight: 800; font-size: 46px; line-height: 1.1; letter-spacing: -0.01em">{e(c['title'])}</h1>
<p style="margin: 0; font-size: 28px; line-height: 1.35; font-weight: 500">{e(c['body'])}</p></div>""")
    return frame(hd, "#6E9BFF", DAY_ICON, "В ЭТОТ ДЕНЬ", c["tag"], plate, handle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("weeks", nargs="+")
    ap.add_argument("--handle", default="@da_eto_pravda")
    ap.add_argument("--out", default=str(ROOT / "cards"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(exist_ok=True)
    hd = head()
    jobs = []
    for wf in a.weeks:
        for p in json.loads(Path(wf).read_text(encoding="utf-8"))["posts"]:
            c = p.get("card_data")
            if not c or not p.get("card"):
                continue
            if p["kind"] == "fact":
                jobs.append((p["card"], fact_card(hd, c, a.handle)))
            elif p["kind"] == "day":
                jobs.append((p["card"], day_card(hd, c, MONTHS[int(p["date"][5:7]) - 1], a.handle)))
    bad = []
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        pg = br.new_page(viewport={"width": 1080, "height": 1080})
        for name, doc in jobs:
            pg.set_content(doc)
            pg.evaluate("document.fonts.ready")
            # текст не влез: содержимое плашки выше самой плашки
            over = pg.evaluate("""() => { const p = document.getElementById('plate');
                return p.scrollHeight > p.clientHeight + 1 || document.getElementById('card').scrollHeight > 1080; }""")
            pg.locator("#card").screenshot(path=str(out / f"{name}.png"))
            print(("✗ не влезает: " if over else "✓ ") + name)
            if over:
                bad.append(name)
        br.close()
    if bad:
        sys.exit(f"Текст не влезает в {len(bad)} карточ(ки): сократите заголовок или текст.")
    print(f"Готово: {len(jobs)} карточек в {out}")


if __name__ == "__main__":
    main()
