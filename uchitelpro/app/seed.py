"""Начальные данные: компетенции, значки, кейсы, демо-пользователи."""
from __future__ import annotations

import json
import sqlite3

from . import config, db, engine, gamification, security

COMPETENCIES = [
    ("COM", "Коммуникация", "Умение слушать, формулировать и выстраивать диалог."),
    ("EMP", "Эмпатия", "Распознавание и учёт эмоций ребёнка и взрослого."),
    ("TAC", "Педагогическая тактика", "Выбор действий в ситуации: остановить, сменить формат, сохранить урок."),
    ("ETH", "Этика и границы", "Объективность, уважение к достоинству, безопасность детей."),
    ("REF", "Рефлексия", "Признание ошибок, фиксация договорённостей, контрольные точки."),
]

DEMO_GROUP = "ПО-21 (демо)"
DEMO_USERS = [
    # login, password, ФИО, роль, must_change
    ("admin", "admin", "Администратор системы", "admin", 1),
    ("methodist", "method123", "Методист Демо", "methodist", 0),
    ("teacher", "teach123", "Преподаватель Демо", "teacher", 0),
    ("student1", "stud123", "Студент Первый (демо)", "student", 0),
    ("student2", "stud123", "Студент Второй (демо)", "student", 0),
]


def graph_of(data: dict) -> dict:
    g = {"start": data["start"], "competencies": data["competencies"], "nodes": data["nodes"]}
    if data.get("meters"):
        g["meters"] = data["meters"]
    for key in ("flag_titles", "flag_print"):
        if data.get(key):
            g[key] = data[key]
    return g


def publish_version(conn: sqlite3.Connection, case_id: int, title: str, graph: dict, review: dict) -> int:
    ana = engine.analyze(graph)
    stats = {k: ana[k] for k in ("best_total", "worst_total", "path_count", "nodes_count", "choices_count")}
    ver = int(db.scalar(conn, "SELECT MAX(version) FROM case_versions WHERE case_id=?", (case_id,), 0)) + 1
    vid = db.insert(conn, "case_versions", case_id=case_id, version=ver, title=title,
                    graph=json.dumps(graph, ensure_ascii=False), review=json.dumps(review, ensure_ascii=False),
                    stats=json.dumps(stats), published_at=db.now())
    conn.execute("UPDATE cases SET current_version_id=?, status='published', title=?, updated_at=? WHERE id=?",
                 (vid, title, db.now(), case_id))
    return vid


def load_builtin_cases(conn: sqlite3.Connection) -> None:
    codes = {r["code"] for r in db.rows(conn, "SELECT code FROM competencies")}
    for path in sorted(config.CASES_DIR.glob("case_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        graph = graph_of(data)
        errs = engine.validate(graph, codes)
        if errs:
            raise RuntimeError(f"Встроенный кейс {path.name} некорректен: {errs}")
        existing = db.one(conn, "SELECT id, current_version_id FROM cases WHERE slug=?", (data["slug"],))
        if existing is None and db.one(conn, "SELECT 1 FROM settings WHERE key=?", ("deleted_case:" + data["slug"],)):
            continue  # встроенный кейс удалён методистом: не возвращаем при перезапуске
        if existing:
            # встроенный кейс обновился в новой версии программы -> публикуем новую версию (старые попытки остаются на своей)
            conn.execute("UPDATE cases SET difficulty=?, duration_min=? WHERE id=?", (data["difficulty"], data["duration_min"], existing["id"]))
            cur = db.one(conn, "SELECT graph, review FROM case_versions WHERE id=?", (existing["current_version_id"],))
            if cur and (json.loads(cur["graph"]) != graph or json.loads(cur["review"]) != data.get("review", {})):
                conn.execute("UPDATE cases SET difficulty=?, duration_min=?, description=? WHERE id=?",
                             (data["difficulty"], data["duration_min"], data["description"], existing["id"]))
                publish_version(conn, existing["id"], data["title"], graph, data.get("review", {}))
            continue
        cid = db.insert(conn, "cases", slug=data["slug"], title=data["title"], category=data["category"],
                        difficulty=data["difficulty"], duration_min=data["duration_min"],
                        description=data["description"], status="draft",
                        created_at=db.now(), updated_at=db.now())
        publish_version(conn, cid, data["title"], graph, data.get("review", {}))


def run(conn: sqlite3.Connection) -> None:
    for code, title, desc in COMPETENCIES:
        if db.one(conn, "SELECT 1 FROM competencies WHERE code=?", (code,)) is None:
            db.insert(conn, "competencies", code=code, title=title, description=desc)
    gamification.seed_badges(conn)
    load_builtin_cases(conn)
    if db.scalar(conn, "SELECT COUNT(*) FROM users", (), 0) == 0:
        gid = db.insert(conn, "groups_", name=DEMO_GROUP, course=2, is_demo=1)
        for login, pwd, name, role, must in DEMO_USERS:
            uid = db.insert(conn, "users", login=login, password_hash=security.hash_password(pwd),
                            full_name=name, role=role, group_id=gid if role == "student" else None,
                            must_change=must, is_demo=1, created_at=db.now())
            if role == "teacher":
                conn.execute("UPDATE groups_ SET teacher_id=? WHERE id=?", (uid, gid))
