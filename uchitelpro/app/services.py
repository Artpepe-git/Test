"""Бизнес-логика, общая для разделов: кейсы, попытки, ассеты, профили."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from . import config, db, engine, gamification

MOODS = ("neutral", "angry", "sad", "happy")
MOOD_RU = {"angry": "злится", "sad": "грустит", "happy": "радуется"}
SCENE_TITLES = {
    "default": "Фон по умолчанию",
    "classroom": "Класс", "classroom_after": "Класс после занятий", "corridor": "Коридор", "office": "Кабинет администратора или координатора",
    "masterclass": "Зал мастер-класса", "foyer": "Холл после мероприятия", "camp_yard": "Двор лагеря", "gym": "Спортивный зал",
    "mansion_hall": "Холл особняка с лестницей",
}
CHARACTER_TITLES = {
    "artem": "Артём", "liza": "Лиза", "irina": "Ирина", "director": "Директор", "student_a": "Ученик",
    "parent": "Родитель", "admin": "Администратор площадки", "coordinator": "Координатор смены", "colleague": "Коллега-вожатый",
    "social_teacher": "Социальный педагог", "teacher_neighbor": "Педагог из соседнего кабинета",
    "timur": "Тимур (протез руки)", "yarik": "Ярик (РАС)", "max": "Макс (ходунки)", "max_mom": "Мама Макса", "dasha": "Даша (коляска)",
}


def asset_title(kind: str, name: str) -> str:
    base = name.split("_")[0] if kind == "characters" and name not in CHARACTER_TITLES else name
    table = SCENE_TITLES if kind == "backgrounds" else CHARACTER_TITLES
    return table.get(name) or table.get(base) or name


# --------------------------------------------------------------------------- ассеты
def asset_url(data_dir: Path, kind: str, name: str, mood: str | None = None) -> str | None:
    """URL файла-ассета, если он положен в data/assets/<kind>/ ; иначе None (покажется контейнер)."""
    if not name:
        return None
    base = Path(data_dir) / "assets" / kind
    candidates = ([f"{name}_{mood}"] if mood else []) + [name]
    for stem in candidates:
        for ext in config.ASSET_EXTS:
            if (base / f"{stem}{ext}").is_file():
                return f"/assets/{kind}/{stem}{ext}"
    return None


def asset_slots(conn: sqlite3.Connection, data_dir: Path) -> list[dict]:
    """Все «контейнеры» под графику: что нужно положить и что уже положено."""
    scenes: dict[str, set[str]] = {}
    chars: dict[str, set[str]] = {}
    for r in db.rows(conn, "SELECT v.graph, c.title FROM cases c JOIN case_versions v ON v.id=c.current_version_id"):
        g = json.loads(r["graph"])
        for node in g["nodes"].values():
            scenes.setdefault(node.get("scene", "default"), set()).add(r["title"])
            for ch in node.get("characters", []):
                chars.setdefault(ch["id"], set()).add(r["title"])
    slots = []
    for scene in sorted(scenes):
        slots.append({"kind": "backgrounds", "name": scene, "label": "Фон: %s" % (SCENE_TITLES.get(scene) or scene),
                      "used": sorted(scenes[scene]), "url": asset_url(data_dir, "backgrounds", scene)})
    for cid in sorted(chars):
        slots.append({"kind": "characters", "name": cid, "label": "Персонаж: %s" % asset_title("characters", cid),
                      "used": sorted(chars[cid]), "url": asset_url(data_dir, "characters", cid)})
        for mood in MOODS[1:]:
            full = asset_url(data_dir, "characters", f"{cid}_{mood}")
            slots.append({"kind": "characters", "name": f"{cid}_{mood}", "label": f"Персонаж: {asset_title('characters', cid)} ({MOOD_RU.get(mood, mood)})",
                          "used": sorted(chars[cid]), "url": full, "optional": True})
    slots.append({"kind": "ui", "name": "mascot", "label": "Талисман платформы", "used": ["интерфейс"],
                  "url": asset_url(data_dir, "ui", "mascot")})
    slots.append({"kind": "ui", "name": "logo", "label": "Логотип", "used": ["интерфейс"],
                  "url": asset_url(data_dir, "ui", "logo")})
    return slots


# --------------------------------------------------------------------------- кейсы
_ANALYSIS_CACHE: dict[str, tuple[dict, engine.Engine]] = {}


def version_bundle(conn: sqlite3.Connection, version_id: int) -> tuple[dict, dict, dict]:
    """Граф, разбор и анализ версии. Версия неизменна, поэтому анализ (перебор состояний) кэшируется по тексту графа."""
    row = db.one(conn, "SELECT graph, review FROM case_versions WHERE id=?", (version_id,))
    graph = json.loads(row["graph"])
    key = hashlib.sha1(row["graph"].encode("utf-8")).hexdigest()
    hit = _ANALYSIS_CACHE.get(key)
    if hit is None:
        if len(_ANALYSIS_CACHE) > 64:
            _ANALYSIS_CACHE.clear()
        eng = engine.Engine(graph)
        hit = _ANALYSIS_CACHE[key] = (engine.analyze(graph, eng), eng)  # движок хранит заполненную таблицу состояний
    return hit[1].g, json.loads(row["review"]), hit[0]


def version_engine(conn: sqlite3.Connection, version_id: int) -> engine.Engine:
    version_bundle(conn, version_id)
    row = db.one(conn, "SELECT graph FROM case_versions WHERE id=?", (version_id,))
    return _ANALYSIS_CACHE[hashlib.sha1(row["graph"].encode("utf-8")).hexdigest()][1]


def visible_cases(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.rows(conn, """SELECT c.*, v.version, v.stats FROM cases c
                            JOIN case_versions v ON v.id=c.current_version_id
                            WHERE c.status='published' ORDER BY c.difficulty, c.id""")


# --------------------------------------------------------------------------- прохождение
def start_attempt(conn: sqlite3.Connection, user_id: int, case_row: sqlite3.Row, practice: bool) -> int:
    existing = db.one(conn, """SELECT id FROM attempts WHERE user_id=? AND case_id=? AND status='in_progress'
                               AND practice=?""", (user_id, case_row["id"], int(practice)))
    if existing:
        return existing["id"]
    graph, _, _ = version_bundle(conn, case_row["current_version_id"])
    first, _ = engine.Engine(graph).start()
    return db.insert(conn, "attempts", user_id=user_id, case_id=case_row["id"],
                     version_id=case_row["current_version_id"], practice=int(practice),
                     current_node=first, started_at=db.now())


def attempt_steps(conn: sqlite3.Connection, attempt_id: int) -> list[sqlite3.Row]:
    return db.rows(conn, "SELECT * FROM attempt_steps WHERE attempt_id=? ORDER BY seq", (attempt_id,))


def step_list(conn: sqlite3.Connection, attempt_id: int) -> list[dict]:
    return [{"node_id": s["node_id"], "choice_id": s["choice_id"]} for s in attempt_steps(conn, attempt_id)]


def play_state(conn: sqlite3.Connection, attempt: sqlite3.Row):
    """(граф, движок, текущий узел, состояние) — состояние восстанавливается переигровкой шагов."""
    graph, _, _ = version_bundle(conn, attempt["version_id"])
    eng = version_engine(conn, attempt["version_id"])
    nid, st = eng.replay(step_list(conn, attempt["id"]))
    return graph, eng, nid, st


def make_choice(conn: sqlite3.Connection, attempt: sqlite3.Row, choice_id: str, spent: int = 0) -> dict:
    """Применяет выбор (или «Далее»). При попадании в финал закрывает попытку."""
    if attempt["status"] != "in_progress":
        raise ValueError("Попытка уже завершена.")
    graph, review, ana = version_bundle(conn, attempt["version_id"])
    eng = version_engine(conn, attempt["version_id"])
    cur, st = eng.replay(step_list(conn, attempt["id"]))
    if cur != attempt["current_node"]:
        raise ValueError("Состояние попытки не совпадает с историей.")
    rating = None
    ch = engine.find_choice(graph, cur, choice_id)
    if ch is not None and eng.available(ch, st):
        rating = eng.rate(cur, st, ch)
    nxt, _, ch = eng.take(cur, st, choice_id)  # ValueError, если вариант закрыт или не существует
    seq = int(db.scalar(conn, "SELECT COUNT(*) FROM attempt_steps WHERE attempt_id=?", (attempt["id"],), 0)) + 1
    conn.execute("BEGIN")
    try:
        db.insert(conn, "attempt_steps", attempt_id=attempt["id"], seq=seq, node_id=cur,
                  choice_id=choice_id, to_node=nxt, scores=json.dumps((ch or {}).get("scores", {})),
                  spent_sec=max(0, min(int(spent), 3600)), created_at=db.now())
        conn.execute("UPDATE attempts SET current_node=? WHERE id=?", (nxt, attempt["id"]))
        finished = engine.is_final(graph["nodes"][nxt])
        if finished:
            _finish(conn, attempt, graph, ana, nxt, eng)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"finished": finished, "rating": rating, "feedback": (ch or {}).get("feedback", "")}


def _finish(conn: sqlite3.Connection, attempt: sqlite3.Row, graph: dict, ana: dict, final_id: str,
            eng: engine.Engine) -> None:
    steps = step_list(conn, attempt["id"])  # шаг, только что вставленный, уже в таблице
    summ = engine.summarize(graph, ana, steps, final_id, eng)
    conn.execute("""UPDATE attempts SET status='finished', final_node=?, outcome=?, score_pct=?, earned=?,
                    best_total=?, stars=?, finished_at=? WHERE id=?""",
                 (final_id, summ["outcome"], summ["pct"], summ["earned"], summ["best_total"], summ["stars"],
                  db.now(), attempt["id"]))
    for row in summ["competencies"]:
        conn.execute("INSERT OR REPLACE INTO attempt_scores(attempt_id, comp_code, earned, max_score) VALUES (?,?,?,?)",
                     (attempt["id"], row["code"], row["earned"], row["max"]))
    if not attempt["practice"]:
        case = db.one(conn, "SELECT difficulty FROM cases WHERE id=?", (attempt["case_id"],))
        xp, _ = gamification.award_case_xp(conn, attempt["user_id"], attempt["case_id"], attempt["version_id"],
                                           attempt["id"], summ["pct"], case["difficulty"])
        conn.execute("UPDATE attempts SET xp_awarded=? WHERE id=?", (xp, attempt["id"]))
        gamification.check_badges(conn, attempt["user_id"])


def attempt_report(conn: sqlite3.Connection, attempt: sqlite3.Row) -> dict:
    graph, review, ana = version_bundle(conn, attempt["version_id"])
    summ = engine.summarize(graph, ana, step_list(conn, attempt["id"]), attempt["final_node"],
                            version_engine(conn, attempt["version_id"]))
    final = graph["nodes"][attempt["final_node"]]
    notes = review.get("node_notes", {})
    for p in summ["path"]:
        p["note"] = notes.get(p["node_id"], "")
    golden = []
    for g in ana["golden_path"]:
        node = graph["nodes"][g["node"]]
        ch = next(c for c in node["choices"] if c["id"] == g["choice"])
        golden.append({"situation": node["text"], "choice_text": ch["text"], "feedback": ch.get("feedback", "")})
    other_finals = [{"id": f, "title": graph["nodes"][f].get("title", f), "outcome": graph["nodes"][f]["outcome"]}
                    for f in ana["reachable_finals"] if f != attempt["final_node"]]
    return {"summary": summ, "review": review, "final": final, "final_id": attempt["final_node"],
            "final_note": review.get("final_notes", {}).get(attempt["final_node"], ""),
            "golden": golden, "comp_titles": comp_titles(conn),
            "golden_final": graph["nodes"][ana["golden_final"]], "other_finals": other_finals,
            "meters_def": graph.get("meters") or []}


def comp_titles(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["code"]: r["title"] for r in db.rows(conn, "SELECT code, title FROM competencies")}


# --------------------------------------------------------------------------- профили и портфолио
def competency_profile(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    """По лучшей зачётной попытке каждого кейса: суммарная доля набранных баллов по компетенциям."""
    rows = db.rows(conn, """
        SELECT s.comp_code, SUM(s.earned) e, SUM(s.max_score) m
        FROM attempt_scores s JOIN attempts a ON a.id=s.attempt_id
        WHERE a.id IN (SELECT id FROM attempts x WHERE x.user_id=? AND x.status='finished' AND x.practice=0
                       AND x.score_pct=(SELECT MAX(score_pct) FROM attempts y WHERE y.user_id=x.user_id
                                        AND y.case_id=x.case_id AND y.status='finished' AND y.practice=0)
                       GROUP BY x.case_id)
        GROUP BY s.comp_code""", (user_id,))
    got = {r["comp_code"]: (r["e"], r["m"]) for r in rows}
    out = []
    for c in db.rows(conn, "SELECT code, title FROM competencies ORDER BY id"):
        e, m = got.get(c["code"], (0, 0))
        out.append({"code": c["code"], "title": c["title"], "pct": round(e / m * 100) if m else None})
    return out


def portfolio_data(conn: sqlite3.Connection, user_id: int) -> dict:
    user = db.one(conn, """SELECT u.*, g.name group_name FROM users u LEFT JOIN groups_ g ON g.id=u.group_id
                           WHERE u.id=?""", (user_id,))
    cases = db.rows(conn, """SELECT c.title, MAX(a.score_pct) pct, MAX(a.stars) stars, COUNT(*) n,
                             MAX(a.finished_at) last
                             FROM attempts a JOIN cases c ON c.id=a.case_id
                             WHERE a.user_id=? AND a.status='finished' AND a.practice=0 GROUP BY c.id
                             ORDER BY last""", (user_id,))
    shifts = db.rows(conn, "SELECT * FROM volunteer_shifts WHERE user_id=? AND status='approved' ORDER BY shift_date",
                     (user_id,))
    notes = db.rows(conn, "SELECT * FROM field_notes WHERE user_id=? AND status IN ('accepted','converted') "
                          "ORDER BY created_at", (user_id,))
    badges = db.rows(conn, """SELECT b.* FROM user_badges ub JOIN badges b ON b.code=ub.badge_code
                              WHERE ub.user_id=? ORDER BY ub.awarded_at""", (user_id,))
    hours = sum(float(s["hours"]) for s in shifts)
    prog = gamification.progress(conn, user_id)
    stamp = f"{user_id}|{prog['xp']}|{hours}|{len(cases)}|{len(notes)}"
    code = hashlib.sha256(("uchitelpro:" + stamp).encode()).hexdigest()[:12].upper()
    return {"user": user, "cases": cases, "shifts": shifts, "notes": notes, "badges": badges, "hours": hours,
            "prog": prog, "competencies": competency_profile(conn, user_id),
            "code": "-".join([code[:4], code[4:8], code[8:]]), "generated": db.now()}


# --------------------------------------------------------------------------- доступ
def can_view_user(conn: sqlite3.Connection, viewer: sqlite3.Row, target_id: int) -> bool:
    if viewer["id"] == target_id or viewer["role"] in ("admin", "methodist"):
        return True
    if viewer["role"] == "teacher":
        return db.one(conn, """SELECT 1 FROM users u JOIN groups_ g ON g.id=u.group_id
                               WHERE u.id=? AND g.teacher_id=?""", (target_id, viewer["id"])) is not None
    return False
