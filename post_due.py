#!/usr/bin/env python3
"""
«Да, это правда» — публикация через бота.

GitHub Actions запускает этот скрипт несколько раз в день. Он смотрит во все файлы week-*.json,
находит посты, время которых подошло, и публикует их в канал через Telegram Bot API.
Что уже отправлено, записывается в sent.json — повторный запуск ничего не задвоит.

Нужны переменные окружения (в GitHub: Settings → Secrets and variables → Actions):
  BOT_TOKEN — токен бота от @BotFather
  CHANNEL   — адрес канала, например @da_eto_pravda
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import publish_week as pw  # общие функции: карточки, фото с Commons, время

HERE = Path(__file__).resolve().parent
SENT_FILE = HERE / "sent.json"
EARLY = timedelta(minutes=10)  # запуск пришёл раньше слота — ждём до точного времени
LATE = timedelta(minutes=90)   # пост опоздал больше чем на полтора часа — не публикуем, отмечаем пропуск


def now_msk() -> datetime:
    return datetime.now(pw.MSK)


class Bot:
    def __init__(self, token: str, channel: str):
        self.api = f"https://api.telegram.org/bot{token}/"
        self.channel = channel

    def call(self, method: str, data: dict, photo: Path = None):
        for attempt in range(5):
            files = None
            fh = None
            try:
                if photo:
                    fh = open(photo, "rb")
                    files = {"photo": (photo.name, fh)}
                r = requests.post(self.api + method, data={"chat_id": self.channel, **data},
                                  files=files, timeout=120)
            finally:
                if fh:
                    fh.close()
            try:
                j = r.json()
            except ValueError:
                j = {"ok": False, "description": r.text[:200]}
            if j.get("ok"):
                return j["result"]
            if r.status_code == 429 or r.status_code >= 500:
                wait = (j.get("parameters") or {}).get("retry_after", 5 * (attempt + 1))
                print(f"    Telegram просит подождать {wait} с…")
                time.sleep(wait + 1)
                continue
            raise RuntimeError(f"{method}: {j.get('description')}")
        raise RuntimeError(f"{method}: Telegram не ответил после нескольких попыток")


def send(bot: Bot, item: dict):
    p = item["post"]
    silent = "true" if p.get("silent", True) else "false"
    if p["kind"] == "quiz":
        q = p["quiz"]
        data = {
            "question": p["text"],
            "options": json.dumps([{"text": o} for o in q["options"]], ensure_ascii=False),
            "type": "quiz",
            "correct_option_id": q["correct"],
            "is_anonymous": "true",
            "disable_notification": silent,
        }
        if q.get("solution"):
            data["explanation"] = q["solution"]
        return bot.call("sendPoll", data)
    if item["image"]:
        return bot.call("sendPhoto", {"caption": item["caption"], "disable_notification": silent},
                        photo=Path(item["image"]))
    return bot.call("sendMessage", {"text": item["caption"], "disable_notification": silent,
                                    "link_preview_options": json.dumps({"is_disabled": True})})


def main():
    token, channel = os.environ.get("BOT_TOKEN"), os.environ.get("CHANNEL")
    if not token or not channel:
        sys.exit("Не заданы BOT_TOKEN и CHANNEL (GitHub → Settings → Secrets and variables → Actions).")
    bot = Bot(token, channel)
    try:
        chat = bot.call("getChat", {})
        print(f"Канал: {chat.get('title')} ({channel}) — бот подключён.")
    except Exception as e:
        sys.exit(f"Бот не видит канал {channel}: {e}. Проверьте токен и что бот — админ канала с правом публикации.")
    sent = json.loads(SENT_FILE.read_text(encoding="utf-8")) if SENT_FILE.exists() else {}
    now = now_msk()

    due = []
    for wf in sorted(HERE.glob("week-*.json")):
        week = json.loads(wf.read_text(encoding="utf-8"))
        for p in week["posts"]:
            key = f"{p['date']} {p['time']}"
            if key in sent:
                continue
            dt = pw.when(p)
            if dt > now + EARLY:
                continue
            if now - dt > LATE:
                sent[key] = {"status": "пропущен: запуск опоздал", "at": now.isoformat(timespec="seconds")}
                print(f"  ! {key}: опоздали больше чем на {int(LATE.total_seconds() // 60)} мин, пропускаю")
                continue
            due.append((dt, key, p))
    due.sort(key=lambda x: x[0])

    failed = 0
    for dt, key, p in due:
        wait = (dt - now_msk()).total_seconds()
        if wait > 0:
            print(f"  жду {int(wait)} с до {p['time']}…")
            time.sleep(wait)
        ready, errors, _ = pw.prepare({"posts": [p]}, no_credit=False, allow_past=True)
        if errors or not ready:
            # без картинки не публикуем: лучше увидеть ошибку и поправить, чем выпустить пост «голым»
            failed += 1
            print(f"  ✗ {key}: " + "; ".join(errors or ["не удалось подготовить пост"]))
            continue
        try:
            msg = send(bot, ready[0])
            sent[key] = {"status": "отправлен", "at": now_msk().isoformat(timespec="seconds"),
                         "message_id": msg.get("message_id")}
            print(f"  ✓ {key} ({p['kind']})")
        except Exception as e:
            failed += 1
            print(f"  ✗ {key}: {e}")
        SENT_FILE.write_text(json.dumps(sent, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    SENT_FILE.write_text(json.dumps(sent, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    if not due:
        print("Сейчас публиковать нечего.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
