#!/usr/bin/env python3
"""Проверка всех будущих постов: карточки на месте, фото существуют на Commons, тексты в лимитах Telegram.
Фото не скачиваются: их наличие проверяется пачками по 50 одним запросом к API Commons — быстро.
Запускается GitHub Actions при каждой загрузке новой недели (check.yml). Ошибка = красная проверка и письмо."""
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish_week as pw  # noqa: E402


def missing_on_commons(titles):
    """Возвращает множество названий, которых нет на Commons (с учётом переименований и редиректов)."""
    missing = set()
    titles = sorted(set(titles))
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        q = urllib.parse.urlencode({"action": "query", "format": "json", "redirects": 1,
                                    "prop": "imageinfo", "iiprop": "url", "titles": "|".join(chunk)})
        data = json.loads(pw.http_get("https://commons.wikimedia.org/w/api.php?" + q))["query"]
        alias = {}
        for n in data.get("normalized", []) + data.get("redirects", []):
            alias[n["from"]] = n["to"]
        found = {pg["title"] for pg in data["pages"].values() if "imageinfo" in pg}
        for t in chunk:
            final = t
            while final in alias:
                final = alias[final]
            if final not in found:
                missing.add(t)
    return missing


total, problems = 0, []
for wf in sorted(ROOT.glob("week-*.json")):
    week = json.loads(wf.read_text(encoding="utf-8"))
    ready, errs, _ = pw.prepare(week, no_credit=False, offline_photos=True)
    total += len(ready)
    problems += [(wf.name, e) for e in errs]
    titles = {i["post"]["photo"]: f"{i['post']['date']} {i['post']['time']}" for i in ready
              if i["post"].get("photo", "").startswith("File:") and not pw.find_photo_override(i["post"]["date"], i["post"]["time"])}
    for t in sorted(missing_on_commons(titles)):
        problems.append((wf.name, f"{titles[t]}: на Commons нет файла «{t}» — нужен другой File:"))
    print(f"{wf.name}: впереди {len(ready)} постов, фото проверено: {len(titles)}")

for name, e in problems:
    print("  ✗", e)
    print(f"::error title={name}::{e}")  # аннотация: видна в GitHub и через API
print(f"Итого впереди {total} постов, проблем {len(problems)}.")
sys.exit(1 if problems else 0)
