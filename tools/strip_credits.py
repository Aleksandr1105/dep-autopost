#!/usr/bin/env python3
"""Разовая правка 10.11.2026: убрать строку «Фото: автор / лицензия, Wikimedia Commons»
из подписей уже опубликованных ботом постов (владелец канала попросил подписи не ставить)."""
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
token, channel = os.environ["BOT_TOKEN"], os.environ["CHANNEL"]
api = f"https://api.telegram.org/bot{token}/"
sent = json.loads((ROOT / "sent.json").read_text(encoding="utf-8"))
posts = {}
for wf in ROOT.glob("week-*.json"):
    for p in json.loads(wf.read_text(encoding="utf-8"))["posts"]:
        posts[f"{p['date']} {p['time']}"] = p
fixed = failed = 0
for key, rec in sorted(sent.items()):
    p = posts.get(key)
    if rec.get("status") != "отправлен" or not rec.get("message_id") or not p or not p.get("photo"):
        continue
    r = requests.post(api + "editMessageCaption", data={"chat_id": channel, "message_id": rec["message_id"],
                                                         "caption": p["text"]}, timeout=60).json()
    if r.get("ok") or "message is not modified" in str(r.get("description")):
        fixed += 1
        print("✓", key)
    else:
        failed += 1
        print("✗", key, r.get("description"))
print(f"Исправлено: {fixed}, ошибок: {failed}")
sys.exit(1 if failed else 0)
