#!/usr/bin/env python3
"""Собирает одностраничную браузерную версию «УчительPRO» в pro/index.html.

Данные берутся из рабочей папки Flask-приложения (uchitelpro/app), поэтому после правки
кейсов достаточно пересобрать страницу:  python3 pro/build.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent / "uchitelpro" / "app"
SRC = HERE / "src"
OUT = HERE / "index.html"

# Демо-версия показывает только эти кейсы. Пустой список — показывать все.
DEMO_SLUGS = ["conflict-5b", "parent-meeting"]

MK_CODE = "ПЕДАГОГ"                       # код для мастер-класса, закрытого от студентов
DOCX_BASE = "../uchitelpro/app/mk/files/"  # .docx лежат в репозитории рядом
IMG_BASE = "img/characters/"               # спрайты персонажей рядом со страницей

COMP = {
    "COM": "Коммуникация",
    "EMP": "Эмпатия",
    "TAC": "Педагогическая тактика",
    "ETH": "Этика и границы",
    "REF": "Рефлексия",
}
SCENES = {
    "default": "", "classroom": "Класс", "classroom_after": "Класс после занятий",
    "corridor": "Коридор", "office": "Кабинет администратора", "masterclass": "Зал мастер-класса",
    "foyer": "Холл после мероприятия", "camp_yard": "Двор лагеря", "gym": "Спортивный зал",
    "mansion_hall": "Холл особняка",
}
CHARS = {
    "artem": "Артём", "liza": "Лиза", "irina": "Ирина", "director": "Директор", "student_a": "Ученик",
    "parent": "Родитель", "admin": "Администратор площадки", "coordinator": "Координатор смены",
    "colleague": "Коллега-вожатый", "social_teacher": "Социальный педагог",
    "teacher_neighbor": "Педагог из соседнего кабинета", "timur": "Тимур", "yarik": "Ярик",
    "max": "Макс", "max_mom": "Мама Макса", "dasha": "Даша",
}
CASE_FIELDS = ("slug", "title", "description", "category", "difficulty", "duration_min",
               "competencies", "start", "nodes", "meters", "flag_titles", "review")


def load_cases() -> list[dict]:
    out = []
    for f in sorted((APP / "cases").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if DEMO_SLUGS and d["slug"] not in DEMO_SLUGS:
            continue
        out.append({k: d[k] for k in CASE_FIELDS if k in d})
    missing = set(DEMO_SLUGS) - {c["slug"] for c in out}
    if missing:
        raise SystemExit("Нет кейсов с такими slug: " + ", ".join(sorted(missing)))
    out.sort(key=lambda c: (c["difficulty"], c["title"]))
    return out


def load_mk() -> list[dict]:
    out = []
    for f in sorted((APP / "mk").glob("*.json")):
        out.append(json.loads(f.read_text(encoding="utf-8")))
    out.sort(key=lambda m: m["total_min"])
    return out


def j(obj) -> str:
    """JSON для вставки в <script>: без переносов строки-разделителя и без закрывающего тега."""
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def main() -> None:
    cases, mk = load_cases(), load_mk()
    data = (
        "const CASES=" + j(cases) + ";\n"
        "const MK=" + j(mk) + ";\n"
        "const COMP=" + j(COMP) + ";\n"
        "const SCENES=" + j(SCENES) + ";\n"
        "const CHARS=" + j(CHARS) + ";\n"
        "const MK_CODE=" + j(MK_CODE) + ";\n"
        "const DOCX_BASE=" + j(DOCX_BASE) + ";\n"
        "const IMG_BASE=" + j(IMG_BASE) + ";\n"
    )
    parts = [
        "<!doctype html>",
        '<html lang="ru">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
        "<title>УчительPRO</title>",
        '<meta name="description" content="Тренажёр педагогических кейсов: ветвящиеся ситуации, разбор по шагам, мастер-классы.">',
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600&display=swap" rel="stylesheet">',
        "<style>", (SRC / "style.css").read_text(encoding="utf-8"), "</style>",
        "</head>",
        "<body>",
        '<div id="wall"></div>',
        '<main class="app" id="app"></main>',
        "<script>", data, "</script>",
        "<script>", (HERE / "qr.js").read_text(encoding="utf-8").replace(
            'if (typeof module !== "undefined") module.exports = QR;', ""), "</script>",
        "<script>", (HERE / "engine.js").read_text(encoding="utf-8"), "</script>",
        "<script>", (SRC / "app.js").read_text(encoding="utf-8"), "</script>",
        "</body>",
        "</html>",
    ]
    html = "\n".join(p for p in parts if p is not None)
    OUT.write_text(html, encoding="utf-8")
    kb = len(html.encode("utf-8")) / 1024
    print(f"{OUT}: {kb:.0f} КБ, кейсов {len(cases)}, мастер-классов {len(mk)}")


if __name__ == "__main__":
    main()
