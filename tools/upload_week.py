#!/usr/bin/env python3
"""
Загрузка недели в репозиторий из пульта: файл недели → карточки → проверка → шифрование.

  python3 tools/upload_week.py <файл недели .json | index.html пульта> [--cards папка_с_png]

- Из index.html пульта (const DAYS = …) собирается файл недели; карточки берутся из --cards
  (PNG из пульта, имена вида 23-fact.png / 23-day.png или «Пн 23.11 · Факт дня.png»).
- Если в файле недели есть card_data, карточки рисуются заново (tools/render_cards.py).
- uploaded.json хранит sha256 загруженного текста недели: если ничего не поменялось, скрипт так и скажет.
- После скрипта остаётся сделать git add / commit / push.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish_week as pw  # noqa: E402

UPLOADED = ROOT / "uploaded.json"


def week_from_pult(html_path: Path, cards_src: Path, out_cards: Path) -> dict:
    h = html_path.read_text(encoding="utf-8")
    a = h.find("const DAYS = ") + len("const DAYS = ")
    days, _ = json.JSONDecoder().raw_decode(h[a:])
    posts = []
    for d in days:
        for p in d["posts"]:
            o = {"date": d["id"], "time": p["t"], "kind": p["kind"], "silent": p["kind"] != "fact", "text": p["text"]}
            if p.get("board"):
                o["card"] = p["board"]
                src = cards_src / Path(p.get("img", "")).name if p.get("img") else None
                if not src or not src.exists():
                    src = cards_src / f"{p['board']}.png"
                shutil.copy(src, out_cards / f"{p['board']}.png")
            if p.get("photo"):
                o["photo"], o["photo_label"] = p["photo"], p.get("label", "")
            if p["kind"] == "quiz":
                o["quiz"] = {"options": p["opts"], "correct": p["ok"], "solution": p["sol"]}
            posts.append(o)
    first = days[0]["id"]
    return {"week_start": first, "timezone": "Europe/Moscow", "posts": posts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--cards", help="папка с PNG карточками (для index.html пульта или если нет card_data)")
    a = ap.parse_args()
    src = Path(a.source)
    cards_dir = ROOT / "cards"

    if src.suffix == ".html":
        week = week_from_pult(src, Path(a.cards), cards_dir)
    else:
        week = json.loads(src.read_text(encoding="utf-8"))
    name = f"week-{week['week_start']}.json"
    text = json.dumps(week, ensure_ascii=False, indent=1, sort_keys=True)
    sha = hashlib.sha256(text.encode()).hexdigest()
    uploaded = json.loads(UPLOADED.read_text(encoding="utf-8")) if UPLOADED.exists() else {}
    if uploaded.get(week["week_start"]) == sha:
        print(f"{name}: без изменений, загружать нечего.")
        return
    (ROOT / name).write_text(text, encoding="utf-8")

    boards = [p["card"] for p in week["posts"] if p.get("card")]
    if any(p.get("card_data") for p in week["posts"]):
        subprocess.run([sys.executable, str(ROOT / "tools" / "render_cards.py"), str(ROOT / name)], check=True)
    elif a.cards and src.suffix != ".html":
        for b in boards:
            shutil.copy(Path(a.cards) / f"{b}.png", cards_dir / f"{b}.png")

    ready, errors, _ = pw.prepare(week, no_credit=False, offline_photos=True)
    if errors:
        for e in errors:
            print("  ✗", e)
        sys.exit("Неделя не загружена: исправьте ошибки.")

    files = [str(ROOT / name)] + [str(cards_dir / f"{b}.png") for b in boards]
    subprocess.run([sys.executable, str(ROOT / "crypto_box.py"), "encrypt", *files], check=True)
    uploaded[week["week_start"]] = sha
    UPLOADED.write_text(json.dumps(uploaded, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{name}: готово к загрузке ({len(ready)} постов, {len(boards)} карточек). Дальше: git add -A, commit, push.")


if __name__ == "__main__":
    main()
