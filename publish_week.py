#!/usr/bin/env python3
"""
«Да, это правда» — автопубликация недели.

Берёт файл недели (week-ГГГГ-ММ-ДД.json, его выгружает кнопка в пульте публикации),
собирает картинки и ставит ВСЕ посты недели в «Отложенные» канала.
Дальше Telegram сам публикует их в нужное время: компьютер и скрипт можно выключить.

Запуск:
  python publish_week.py week-2026-11-09.json --check   проверка без входа в Telegram
  python publish_week.py week-2026-11-09.json           поставить посты в отложенные
"""
import argparse
import asyncio
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "settings.json"
CARDS_DIR = HERE / "cards"
PHOTOS_DIR = HERE / "photos"
CACHE_DIR = HERE / "cache"
LOG_FILE = HERE / "publish-log.txt"

MSK = timezone(timedelta(hours=3))  # Москва, UTC+3 круглый год
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
UA = "DaEtoPravdaPublisher/1.0 (Telegram channel autoposting script)"

# Ограничения Telegram
CAPTION_MAX = 1024        # подпись к фото (без Premium)
TEXT_MAX = 4096           # обычное сообщение
QUIZ_Q_MAX, QUIZ_OPT_MAX, QUIZ_SOL_MAX = 300, 100, 200
SCHEDULED_MAX = 100       # отложенных сообщений в одном чате

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def norm(s: str) -> str:
    """'Пн 9.11 · Факт дня' -> 'пн911фактдня' — чтобы имя файла карточки совпадало при любых пробелах и точках."""
    return re.sub(r"[\W_]+", "", s.lower())


def log(msg: str) -> None:
    print(msg)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


# ---------- картинки ----------

def find_card(board: str):
    if not CARDS_DIR.exists():
        return None
    want = norm(board)
    for p in CARDS_DIR.iterdir():
        if p.suffix.lower() in IMG_EXT and norm(p.stem) == want:
            return p
    return None


def find_photo_override(date: str, time: str):
    """Своё фото вместо Commons: photos/2026-11-13 19-30.jpg"""
    if not PHOTOS_DIR.exists():
        return None
    want = norm(f"{date} {time}")
    for p in PHOTOS_DIR.iterdir():
        if p.suffix.lower() in IMG_EXT and norm(p.stem) == want:
            return p
    return None


# Обычная проверка сертификатов остаётся; снимаем только «строгий» режим новых Python,
# который ломается, когда антивирус проверяет HTTPS и подставляет свой сертификат.
SSL_CTX = ssl.create_default_context()
SSL_CTX.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)


def http_get(url: str) -> bytes:
    """Запрос с паузами: Wikimedia отвечает 429, если спрашивать слишком часто."""
    for attempt in range(6):
        time.sleep(1.0)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 5:
                wait = int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
                print(f"    Wikimedia просит подождать {wait} с…")
                time.sleep(min(wait, 60))
                continue
            raise


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def commons_photo(file_title: str):
    """Скачивает фото с Wikimedia Commons (1280 px — стандартный размер Wikimedia) и возвращает (путь, строка автора и лицензии)."""
    CACHE_DIR.mkdir(exist_ok=True)
    meta_path = CACHE_DIR / (norm(file_title)[:80] + ".json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if Path(meta["path"]).exists():
            return Path(meta["path"]), meta["credit"]
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "redirects": 1, "titles": file_title,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1280,
    })
    data = json.loads(http_get("https://commons.wikimedia.org/w/api.php?" + q))
    page = next(iter(data["query"]["pages"].values()))
    if "imageinfo" not in page:
        raise RuntimeError(f"на Commons нет файла «{file_title}»")
    info = page["imageinfo"][0]
    url = info.get("thumburl") or info["url"]
    md = info.get("extmetadata", {})
    artist = strip_html(md.get("Artist", {}).get("value", ""))[:80] or "автор не указан"
    lic = strip_html(md.get("LicenseShortName", {}).get("value", "")) or "свободная лицензия"
    credit = f"Фото: {artist} / {lic}, Wikimedia Commons"
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if ext not in IMG_EXT:
        ext = ".jpg"
    path = CACHE_DIR / (norm(file_title)[:80] + ext)
    path.write_bytes(http_get(url))
    meta_path.write_text(json.dumps({"path": str(path), "credit": credit}, ensure_ascii=False), encoding="utf-8")
    return path, credit


# ---------- подготовка ----------

def when(post) -> datetime:
    return datetime.strptime(f"{post['date']} {post['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=MSK)


def prepare(week: dict, no_credit: bool, allow_past: bool = False):
    """Проверяет посты и находит картинки. Возвращает (готовые посты, ошибки, предупреждения)."""
    ready, errors, warns = [], [], []
    now = datetime.now(MSK)
    for p in week["posts"]:
        tag = f"{p['date']} {p['time']} ({p['kind']})"
        try:
            dt = when(p)
        except ValueError:
            errors.append(f"{tag}: не читается дата или время")
            continue
        if not allow_past and dt < now + timedelta(minutes=2):
            warns.append(f"{tag}: время уже прошло, пост пропущен")
            continue
        item = {"post": p, "when": dt, "tag": tag, "image": None, "caption": p["text"]}

        if p["kind"] == "quiz":
            q = p.get("quiz") or {}
            opts = q.get("options") or []
            if len(p["text"]) > QUIZ_Q_MAX:
                errors.append(f"{tag}: вопрос длиннее {QUIZ_Q_MAX} символов")
            if not 2 <= len(opts) <= 10 or any(len(o) > QUIZ_OPT_MAX for o in opts):
                errors.append(f"{tag}: нужно 2–10 вариантов, каждый до {QUIZ_OPT_MAX} символов")
            if not isinstance(q.get("correct"), int) or not 0 <= q["correct"] < len(opts):
                errors.append(f"{tag}: не указан верный вариант")
            if len(q.get("solution", "")) > QUIZ_SOL_MAX:
                errors.append(f"{tag}: пояснение к ответу длиннее {QUIZ_SOL_MAX} символов")
            ready.append(item)
            continue

        if p.get("card"):
            img = find_card(p["card"])
            if not img:
                errors.append(f"{tag}: нет карточки — положите в папку cards файл «{p['card']}.png»")
            item["image"] = img
        elif p.get("photo"):
            img = find_photo_override(p["date"], p["time"])
            if img:
                item["image"] = img
            elif p["photo"].startswith("Category:"):
                errors.append(f"{tag}: в пульте подборка, а не одно фото — выберите фото и положите его "
                              f"в папку photos под именем «{p['date']} {p['time'].replace(':', '-')}.jpg»")
            else:
                try:
                    print(f"  фото {tag}…")
                    img, credit = commons_photo(p["photo"])
                    item["image"] = img
                    if not no_credit:
                        item["caption"] = p["text"] + "\n\n" + credit
                except Exception as e:  # сеть, удалённый файл и т. п.
                    errors.append(f"{tag}: фото не скачалось ({e}). Можно положить своё в photos/"
                                  f"«{p['date']} {p['time'].replace(':', '-')}.jpg»")

        limit = CAPTION_MAX if (p.get("card") or p.get("photo")) else TEXT_MAX
        if len(item["caption"]) > limit:
            errors.append(f"{tag}: текст {len(item['caption'])} символов, а в подписи к фото максимум {limit}")
        ready.append(item)

    times = [i["when"] for i in ready]
    dup = {t for t in times if times.count(t) > 1}
    for t in sorted(dup):
        errors.append(f"{t:%Y-%m-%d %H:%M}: на это время стоит больше одного поста")
    return ready, errors, warns


# ---------- Telegram ----------

def load_settings():
    if not SETTINGS.exists():
        SETTINGS.write_text(json.dumps({
            "api_id": 0, "api_hash": "ВСТАВЬТЕ_API_HASH", "channel": "@ваш_канал"
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit(f"Создан файл {SETTINGS.name}. Впишите в него api_id, api_hash и канал (см. README-instrukciya.md) и запустите снова.")
    s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    if not s.get("api_id") or "ВСТАВЬТЕ" in str(s.get("api_hash")) or "ваш_канал" in str(s.get("channel")):
        sys.exit(f"Заполните {SETTINGS.name}: api_id, api_hash и channel.")
    return s


async def publish(ready, settings):
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError
    from telethon.tl.types import InputMediaPoll, Poll, PollAnswer, TextWithEntities

    client = TelegramClient(str(HERE / "dep_session"), int(settings["api_id"]), settings["api_hash"],
                            flood_sleep_threshold=300)
    client.parse_mode = None  # текст уходит как есть, без разметки
    await client.start()
    ch = settings["channel"]
    if isinstance(ch, str) and re.fullmatch(r"-?\d+", ch):
        ch = int(ch)
    channel = await client.get_entity(ch)

    existing = [m async for m in client.iter_messages(channel, scheduled=True)]
    taken = {m.date.astimezone(timezone.utc).replace(second=0, microsecond=0) for m in existing}
    todo = [i for i in ready if i["when"].astimezone(timezone.utc) not in taken]
    skipped = len(ready) - len(todo)
    if skipped:
        log(f"Уже стоят в отложенных: {skipped} — их пропускаю (повторный запуск ничего не задвоит).")
    if len(existing) + len(todo) > SCHEDULED_MAX:
        await client.disconnect()
        sys.exit(f"В отложенных уже {len(existing)}, добавить нужно {len(todo)} — это больше лимита Telegram "
                 f"({SCHEDULED_MAX}). Подождите, пока часть опубликуется, и запустите снова.")

    ok = failed = 0
    for i in todo:
        p = i["post"]
        try:
            if p["kind"] == "quiz":
                q = p["quiz"]
                poll = Poll(
                    id=int(i["when"].timestamp()),
                    question=TextWithEntities(text=p["text"], entities=[]),
                    answers=[PollAnswer(text=TextWithEntities(text=o, entities=[]), option=str(n).encode())
                             for n, o in enumerate(q["options"])],
                    quiz=True,
                )
                media = InputMediaPoll(poll=poll, correct_answers=[str(q["correct"]).encode()],
                                       solution=q.get("solution") or None,
                                       solution_entities=[] if q.get("solution") else None)
                await client.send_file(channel, media, schedule=i["when"], silent=p.get("silent", True))
            elif i["image"]:
                await client.send_file(channel, str(i["image"]), caption=i["caption"],
                                       schedule=i["when"], silent=p.get("silent", True))
            else:
                await client.send_message(channel, i["caption"], schedule=i["when"],
                                          silent=p.get("silent", True), link_preview=False)
            ok += 1
            log(f"  ✓ {i['tag']}")
        except FloodWaitError as e:
            log(f"  Telegram просит паузу {e.seconds} с — жду…")
            await asyncio.sleep(e.seconds + 5)
            failed += 1
            log(f"  ✗ {i['tag']}: пропущен из-за паузы, запустите скрипт ещё раз — он доставит только недостающее")
        except Exception as e:
            failed += 1
            log(f"  ✗ {i['tag']}: {type(e).__name__}: {e}")
        await asyncio.sleep(1.5)  # не торопимся, чтобы Telegram не ограничивал

    await client.disconnect()
    log(f"Готово: поставлено {ok}, ошибок {failed}, уже было {skipped}. "
        f"Проверьте канал → значок часов «Отложенные».")
    return failed


def main():
    ap = argparse.ArgumentParser(description="Поставить неделю постов в отложенные канала.")
    ap.add_argument("week", help="файл недели, например week-2026-11-09.json")
    ap.add_argument("--check", action="store_true", help="только проверить и скачать картинки, без входа в Telegram")
    ap.add_argument("--no-credit", action="store_true", help="не добавлять строку «Фото: автор / лицензия»")
    ap.add_argument("--force", action="store_true", help="ставить посты, даже если у части не нашлась картинка")
    a = ap.parse_args()

    week = json.loads(Path(a.week).read_text(encoding="utf-8"))
    log(f"Неделя {week.get('week_start', '?')}: {len(week['posts'])} постов. Проверяю и собираю картинки…")
    ready, errors, warns = prepare(week, a.no_credit)
    for w in warns:
        log("  ! " + w)
    for e in errors:
        log("  ✗ " + e)

    by_kind = {}
    for i in ready:
        by_kind[i["post"]["kind"]] = by_kind.get(i["post"]["kind"], 0) + 1
    log(f"К публикации: {len(ready)} ({', '.join(f'{k}: {v}' for k, v in by_kind.items())}).")

    if errors and not a.force:
        sys.exit(f"Найдено проблем: {len(errors)}. Исправьте их (или запустите с --force, "
                 f"тогда посты без картинки уйдут только текстом) и запустите снова.")
    if a.check:
        log("Проверка пройдена." if not errors else "Проверка закончена, есть проблемы (см. выше).")
        return
    if a.force:
        for i in ready:
            if i["image"] is None and (i["post"].get("card") or i["post"].get("photo")):
                i["caption"] = i["post"]["text"]
    sys.exit(1 if asyncio.run(publish(ready, load_settings())) else 0)


if __name__ == "__main__":
    main()
