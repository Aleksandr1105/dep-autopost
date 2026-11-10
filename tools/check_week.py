#!/usr/bin/env python3
"""Проверка всех будущих постов: карточки на месте, фото существуют и НЕ требуют указания автора, тексты в лимитах Telegram.

Фото бывают двух видов:
- `File:…` с Wikimedia Commons — проверяются пачками по 50 через API Commons: файл существует и его лицензия
  не требует подписи (AttributionRequired = false: общественное достояние, CC0 и т. п.);
- прямая ссылка `https://…` на сайт из списка publish_week.FREE_PHOTO_HOSTS (Unsplash, Pexels, Pixabay, NASA) —
  проверяется, что по ссылке скачивается картинка.

Владелец канала решил не ставить подписи об авторе (10.11.2026), поэтому фото с CC BY / CC BY-SA не годятся.
Запускается GitHub Actions при каждой загрузке новой недели (check.yml). Ошибка = красная проверка и письмо."""
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish_week as pw  # noqa: E402


def commons_status(titles):
    """Возвращает {название: None | «нет файла» | «нужна подпись (лицензия)»}."""
    result = {}
    titles = sorted(set(titles))
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        q = urllib.parse.urlencode({"action": "query", "format": "json", "redirects": 1,
                                    "prop": "imageinfo", "iiprop": "extmetadata", "titles": "|".join(chunk)})
        data = json.loads(pw.http_get("https://commons.wikimedia.org/w/api.php?" + q))["query"]
        alias = {n["from"]: n["to"] for n in data.get("normalized", []) + data.get("redirects", [])}
        pages = {pg["title"]: pg for pg in data["pages"].values()}
        for t in chunk:
            final = t
            while final in alias:
                final = alias[final]
            pg = pages.get(final, {})
            if "imageinfo" not in pg:
                result[t] = "на Commons нет такого файла"
                continue
            md = pg["imageinfo"][0].get("extmetadata", {})
            lic = pw.strip_html(md.get("LicenseShortName", {}).get("value", "")) or "?"
            attr = str(md.get("AttributionRequired", {}).get("value", "true")).lower()
            result[t] = None if attr == "false" else f"лицензия «{lic}» требует подписи автора — нужно фото в общественном достоянии / CC0"
    return result


def url_status(url):
    try:
        pw.url_photo(url)
        return None
    except Exception as e:
        return f"ссылка на фото не работает ({e})"


total, problems = 0, []
for wf in sorted(ROOT.glob("week-*.json")):
    week = json.loads(wf.read_text(encoding="utf-8"))
    ready, errs, _ = pw.prepare(week, no_credit=True, offline_photos=True)
    total += len(ready)
    problems += [(wf.name, e) for e in errs]
    files, urls = {}, {}
    for i in ready:
        p = i["post"]
        ph = p.get("photo", "")
        if not ph or pw.find_photo_override(p["date"], p["time"]):
            continue
        where = f"{p['date']} {p['time']}"
        if ph.startswith("File:"):
            files[ph] = where
        elif ph.startswith("http"):
            urls[ph] = where
    for t, msg in sorted(commons_status(files).items()):
        if msg:
            problems.append((wf.name, f"{files[t]}: «{t}» — {msg}"))
    for u, where in sorted(urls.items()):
        msg = url_status(u)
        if msg:
            problems.append((wf.name, f"{where}: {msg}: {u}"))
    print(f"{wf.name}: впереди {len(ready)} постов, фото проверено: {len(files) + len(urls)}")

for name, e in problems:
    print("  ✗", e)
# одна аннотация на неделю со всеми проблемами (у GitHub лимит на число аннотаций); видна через API без авторизации
by_week = {}
for name, e in problems:
    by_week.setdefault(name, []).append(e)
for name, errs in by_week.items():
    # коротко: только дата и время постов с проблемами (полный текст — в логе); длинные аннотации GitHub обрезает
    slots = [e.split(": ", 1)[0] for e in errs]
    print(f"::error title={name} ({len(errs)})::" + ", ".join(slots))
print(f"Итого впереди {total} постов, проблем {len(problems)}.")
sys.exit(1 if problems else 0)
