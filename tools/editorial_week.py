#!/usr/bin/env python3
"""Validate a channel week and build the private review package."""

import argparse
import base64
import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish_week

DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
QUIZ_DAYS = (0, 2, 4, 6)
ANSWER_DAYS = (0, 1, 3, 5)
SCHEDULE = {
    "08:00": "fact", "09:00": "day", "10:30": "short", "12:00": "short",
    "13:30": "long", "15:00": "short", "16:30": "short", "18:00": "short",
    "19:30": "long",
}
RUBRICS = {"fact": "✅ Факт дня", "day": "🗓 В этот день",
           "quiz": "❓ Вопрос дня", "answer": "💡 Ответ на вчерашний вопрос:"}
TOPIC_ICONS = set("🐾🌿🌍🔭🧬⚡⚙🏛🔢💰")
CHROMIUM_URL = "https://registry.npmjs.org/@sparticuz/chromium/-/chromium-153.0.0.tgz"
CHROMIUM_SHA256 = "20e5656fcdcf4118ede85edfb9d6bb9cc1bbb7ffb8b75622fffbcf36a835c3c0"


def canonical(week):
    return json.dumps(week, ensure_ascii=False, indent=1, sort_keys=True).encode()


def schedule(monday):
    slots = {}
    for index in range(7):
        day = (monday + timedelta(days=index)).isoformat()
        if index in ANSWER_DAYS:
            slots[day, "07:30"] = "answer"
        slots.update({(day, time): kind for time, kind in SCHEDULE.items()})
        slots[day, "21:00"] = "quiz" if index in QUIZ_DAYS else "short"
    return slots


def validate(week, sources):
    monday = date.fromisoformat(week["week_start"])
    if monday.weekday() or week["timezone"] != "Europe/Moscow":
        raise ValueError("Неделя должна начинаться в понедельник, часовой пояс Europe/Moscow.")
    expected = schedule(monday)
    posts = week["posts"]
    slots = [(p["date"], p["time"]) for p in posts]
    if slots != list(expected):
        raise ValueError("Нужны все 74 слота недели в хронологическом порядке.")
    if set(sources) != {f"{d} {t}" for d, t in slots}:
        raise ValueError("В sources.json нужен источник для каждого слота.")

    allowed = {"date", "time", "kind", "silent", "text", "card",
               "card_data", "photo", "photo_label", "quiz"}
    for slot, p in zip(slots, posts):
        where = " ".join(slot)
        kind = expected[slot]
        text = p["text"]
        if p.keys() - allowed or p["kind"] != kind or p["silent"] is not (kind != "fact"):
            raise ValueError(f"{where}: проверьте поля, рубрику и уведомления.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{where}: нет текста.")
        if kind in RUBRICS and not text.startswith(RUBRICS[kind]):
            raise ValueError(f"{where}: неверная метка рубрики.")
        if kind in ("short", "long") and text[0] not in TOPIC_ICONS:
            raise ValueError(f"{where}: неверная метка темы.")
        if ("quiz" in p) != (kind == "quiz"):
            raise ValueError(f"{where}: поле quiz допустимо только у вопроса и обязательно для него.")
        if kind in ("fact", "day"):
            day = date.fromisoformat(p["date"])
            board = f"{DAYS[day.weekday()]} {day:%d.%m} · {RUBRICS[kind].split(' ', 1)[1]}"
            fields = {"tag", "title", "body"}
            if kind == "day":
                fields |= {"d", "y"}
            data = p.get("card_data", {})
            if p.get("card") != board or set(data) != fields:
                raise ValueError(f"{where}: проверьте имя и поля карточки.")
            if kind == "day" and (str(data["d"]).lstrip("0") != str(day.day)
                                  or not str(data["y"]).isdigit()):
                raise ValueError(f"{where}: проверьте день и год на карточке.")
        elif {"card", "card_data"} & p.keys():
            raise ValueError(f"{where}: карточка допустима только у двух рубрик.")
        if p.get("photo"):
            photo = p["photo"]
            direct = photo.startswith("https://") and publish_week.photo_host_ok(photo)
            if kind not in ("short", "long") or not (photo.startswith("File:") or direct):
                raise ValueError(f"{where}: недопустимое фото.")
            if not p.get("photo_label"):
                raise ValueError(f"{where}: нужно название фото для пульта.")
        links = sources[where]
        if (not isinstance(links, list) or not links or
                any(not isinstance(url, str) or not url.startswith("https://") for url in links)):
            raise ValueError(f"{where}: нужны ссылки на проверенные источники.")
    return monday


def browser_environment(cache):
    env = os.environ.copy()
    cache.mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(cache.resolve())
    if env.get("DEP_CARD_CHROMIUM"):
        return env

    executable = cache / "chromium"
    if not executable.exists():
        package = cache / "chromium.tgz"
        with urllib.request.urlopen(CHROMIUM_URL, timeout=90) as response, package.open("wb") as out:
            shutil.copyfileobj(response, out)
        with package.open("rb") as data:
            if hashlib.file_digest(data, "sha256").hexdigest() != CHROMIUM_SHA256:
                raise ValueError("Контрольная сумма Chromium не совпала.")
        compressed = cache / "chromium.br"
        with tarfile.open(package, "r:gz") as archive:
            with archive.extractfile("package/bin/chromium.br") as entry, compressed.open("wb") as out:
                shutil.copyfileobj(entry, out)
        temporary = cache / "chromium.tmp"
        subprocess.run([
            "node", "-e",
            "const fs=require('node:fs'); const z=require('node:zlib'); "
            "require('node:stream/promises').pipeline(fs.createReadStream(process.argv[1]), "
            "z.createBrotliDecompress(), fs.createWriteStream(process.argv[2],{mode:0o700}))"
            ".catch(err=>{console.error(err);process.exitCode=1});",
            str(compressed), str(temporary),
        ], check=True)
        temporary.replace(executable)
        package.unlink()
        compressed.unlink()
    env["DEP_CARD_CHROMIUM"] = str(executable.resolve())
    return env


def links_markup(urls):
    return " · ".join(f'<a href="{html.escape(url, quote=True)}">Источник {i}</a>'
                      for i, url in enumerate(urls, 1))


def post_markup(post, sources, cards):
    time = html.escape(post["time"])
    text = html.escape(post["text"]).replace("\n", "<br>")
    parts = [f'<article><time>{time}</time><p>{text}</p>']
    if post.get("card"):
        card = cards / f'{post["card"]}.png'
        data = base64.b64encode(card.read_bytes()).decode("ascii")
        parts.append(f'<img loading="lazy" src="data:image/png;base64,{data}" alt="{html.escape(post["card"])}">')
    if post.get("photo"):
        photo = post["photo"]
        url = (photo if photo.startswith("https://") else
               "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(photo.replace(" ", "_")))
        parts.append(f'<p>Фото · <a href="{html.escape(url)}">{html.escape(post["photo_label"])}</a></p>')
    if post.get("quiz"):
        quiz = post["quiz"]
        choices = "".join(f"<li>{html.escape(option)}{' ✓' if i == quiz['correct'] else ''}</li>"
                          for i, option in enumerate(quiz["options"]))
        parts.append(f"<ol>{choices}</ol><p>{html.escape(quiz['solution'])}</p>")
    parts.append(f"<p>{links_markup(sources)}</p></article>")
    return "".join(parts)


def dashboard(week, sources, cards, monday):
    sunday = monday + timedelta(days=6)
    title = f"Пульт недели {monday:%d.%m}–{sunday:%d.%m.%Y}"
    tabs, sections = [], []
    for i, label in enumerate(DAYS):
        day = monday + timedelta(days=i)
        value = day.isoformat()
        tabs.append(f'<button type="button" aria-pressed="{str(i == 0).lower()}" data-day="{value}">{label} {day:%d.%m}</button>')
        items = (post_markup(p, sources[f"{value} {p['time']}"], cards)
                 for p in week["posts"] if p["date"] == value)
        sections.append(f'<section id="{value}"{" hidden" if i else ""}>{"".join(items)}</section>')
    return f"""<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}body{{max-width:860px;margin:0 auto;padding:24px;color:#181818;background:#f6f7f9;font:16px/1.55 system-ui,sans-serif}}
h1{{line-height:1.15}}nav{{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}}
button{{font:inherit;background:white;border:1px solid #777;border-radius:8px;padding:8px 12px;cursor:pointer}}
button[aria-pressed=true]{{background:#181818;color:white}}article{{background:white;border:1px solid #dedede;border-radius:12px;padding:18px;margin:12px 0}}
time{{font-weight:700}}img{{display:block;max-width:420px;width:100%;height:auto}}a{{color:#1749a4}}
</style>
<h1>{title}</h1><p>Публикуется автоматически. Правки пишите в чат — я поправлю до публикации</p>
<nav aria-label="Дни недели">{"".join(tabs)}</nav><main>{"".join(sections)}</main>
<script>
const buttons = document.querySelectorAll('button[data-day]');
for (const button of buttons) {{
  button.addEventListener('click', () => {{
    for (const item of buttons) {{
      const selected = item === button;
      item.setAttribute('aria-pressed', String(selected));
      document.getElementById(item.dataset.day).hidden = !selected;
    }}
  }});
}}
</script></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("week", type=Path)
    parser.add_argument("sources", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--browser-cache", type=Path, required=True)
    args = parser.parse_args()
    week = json.loads(args.week.read_text(encoding="utf-8"))
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    monday = validate(week, sources)
    args.out.mkdir(parents=True, exist_ok=True)
    cards = args.out / "cards"
    cards.mkdir(exist_ok=True)
    week_file = args.out / "week.json"
    week_file.write_bytes(canonical(week))
    env = browser_environment(args.browser_cache)
    subprocess.run([sys.executable, str(ROOT / "tools" / "render_cards.py"),
                    str(week_file), "--out", str(cards)], check=True, env=env)
    publish_week.CARDS_DIR = cards
    ready, errors, _ = publish_week.prepare(week, no_credit=True, allow_past=True, offline_photos=True)
    if errors or len(ready) != 74:
        raise ValueError("\n".join(errors) or "Проверка подтвердила меньше 74 постов.")
    index = args.out / "index.html"
    index.write_text(dashboard(week, sources, cards, monday), encoding="utf-8")
    with ZipFile(args.out / f"pult-{monday}.zip", "w", compression=ZIP_DEFLATED) as archive:
        archive.write(index, "index.html")
        archive.write(week_file, "week.json")
        archive.writestr("sources.json", json.dumps(sources, ensure_ascii=False, indent=2))
        for post in week["posts"]:
            if post.get("card"):
                name = f'{post["card"]}.png'
                archive.write(cards / name, f"cards/{name}")
    print(f"{monday}: 74 поста, 14 карточек. SHA256 {hashlib.sha256(week_file.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
