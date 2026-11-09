#!/usr/bin/env python3
"""Проверка всех будущих постов: карточки на месте, фото скачиваются с Commons, тексты в лимитах Telegram.
Запускается GitHub Actions при каждой загрузке новой недели (check.yml). Ошибка = письмо владельцу."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish_week as pw  # noqa: E402

total = errors = 0
for wf in sorted(ROOT.glob("week-*.json")):
    week = json.loads(wf.read_text(encoding="utf-8"))
    ready, errs, _ = pw.prepare(week, no_credit=False)
    total += len(ready)
    print(f"{wf.name}: впереди {len(ready)} постов, проблем {len(errs)}")
    for e in errs:
        print("  ✗", e)
    errors += len(errs)
print(f"Итого впереди {total} постов.")
sys.exit(f"Найдено проблем: {errors}" if errors else 0)
