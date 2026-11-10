"""XP, уровни, значки, анти-накрутка."""
from __future__ import annotations

import math
import sqlite3

from . import db

DAILY_CASE_XP_LIMIT = 300
REPEAT_FACTORS = (1.0, 0.5, 0.25)  # 1-е, 2-е, 3-е и далее прохождения одной версии кейса
VOLUNTEER_XP_PER_HOUR = 15
VOLUNTEER_XP_MAX_PER_SHIFT = 90
NOTE_ACCEPTED_XP = 30
NOTE_CONVERTED_XP = 60

BADGES = [
    ("first_case", "Первый шаг", "Пройден первый кейс.", "🌱"),
    ("three_stars", "Мастер диалога", "Кейс пройден на три звезды.", "🌟"),
    ("both_cases", "Исследователь", "Пройдено не менее двух разных кейсов.", "🧭"),
    ("level_3", "Уверенный практик", "Достигнут 3-й уровень.", "🎖"),
    ("level_5", "Наставник", "Достигнут 5-й уровень.", "🏆"),
    ("volunteer_first", "Волонтёрский старт", "Первая подтверждённая смена.", "🤝"),
    ("volunteer_10h", "10 часов добра", "10 подтверждённых часов волонтёрства.", "⏱"),
    ("note_accepted", "Полевой исследователь", "Заметка принята методистом.", "📝"),
    ("note_converted", "Автор кейса", "По вашей заметке создан кейс.", "✍"),
]


def level_for(xp: int) -> tuple[int, int, int]:
    """(уровень, xp начала уровня, xp начала следующего). Порог уровня L: 50*L*(L-1)."""
    lvl = 1
    while 50 * (lvl + 1) * lvl <= xp:
        lvl += 1
    return lvl, 50 * lvl * (lvl - 1), 50 * (lvl + 1) * lvl


def total_xp(conn: sqlite3.Connection, user_id: int) -> int:
    return int(db.scalar(conn, "SELECT SUM(xp) FROM xp_events WHERE user_id=?", (user_id,), 0))


def progress(conn: sqlite3.Connection, user_id: int) -> dict:
    xp = total_xp(conn, user_id)
    lvl, lo, hi = level_for(xp)
    return {"xp": xp, "level": lvl, "lo": lo, "hi": hi,
            "pct": round((xp - lo) / (hi - lo) * 100) if hi > lo else 100}


def seed_badges(conn: sqlite3.Connection) -> None:
    for code, title, desc, icon in BADGES:
        if db.one(conn, "SELECT 1 FROM badges WHERE code=?", (code,)) is None:
            db.insert(conn, "badges", code=code, title=title, description=desc, icon=icon)


def add_xp(conn: sqlite3.Connection, user_id: int, source_type: str, source_id: int | None,
           xp: int, note: str = "") -> int:
    if xp == 0:
        return 0
    db.insert(conn, "xp_events", user_id=user_id, source_type=source_type, source_id=source_id,
              xp=xp, note=note, created_at=db.now())
    return xp


def award_badge(conn: sqlite3.Connection, user_id: int, code: str) -> bool:
    if db.one(conn, "SELECT 1 FROM user_badges WHERE user_id=? AND badge_code=?", (user_id, code)):
        return False
    db.insert(conn, "user_badges", user_id=user_id, badge_code=code, awarded_at=db.now())
    return True


def case_xp(pct: float, difficulty: int) -> int:
    return round((30 + 50 * pct) * (0.8 + 0.2 * max(1, difficulty)))


def award_case_xp(conn: sqlite3.Connection, user_id: int, case_id: int, version_id: int,
                  attempt_id: int, pct: float, difficulty: int) -> tuple[int, str]:
    """Начисляет XP за завершённую (не тренировочную) попытку. Возвращает (xp, пояснение)."""
    base = case_xp(pct, difficulty)
    prev = int(db.scalar(conn, """SELECT COUNT(*) FROM attempts WHERE user_id=? AND version_id=?
                                  AND practice=0 AND status='finished' AND id<>?""",
                         (user_id, version_id, attempt_id), 0))
    factor = REPEAT_FACTORS[min(prev, len(REPEAT_FACTORS) - 1)]
    xp = round(base * factor)
    note = f"Кейс, попытка №{prev + 1}"
    if prev:
        note += f" (коэффициент {factor})"
    today = db.now()[:10]
    got = int(db.scalar(conn, """SELECT SUM(xp) FROM xp_events WHERE user_id=? AND source_type='case'
                                 AND substr(created_at,1,10)=?""", (user_id, today), 0))
    room = max(0, DAILY_CASE_XP_LIMIT - got)
    if xp > room:
        xp = room
        note += "; достигнут дневной лимит XP"
    add_xp(conn, user_id, "case", attempt_id, xp, note)
    return xp, note


def volunteer_xp(hours: float) -> int:
    return min(VOLUNTEER_XP_MAX_PER_SHIFT, round(hours * VOLUNTEER_XP_PER_HOUR))


def check_badges(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """Проверяет все условия, возвращает коды новых значков."""
    new: list[str] = []

    def give(code: str, cond: bool) -> None:
        if cond and award_badge(conn, user_id, code):
            new.append(code)

    fin = db.scalar(conn, "SELECT COUNT(*) FROM attempts WHERE user_id=? AND status='finished' AND practice=0",
                    (user_id,), 0)
    give("first_case", fin >= 1)
    give("three_stars", db.scalar(conn, "SELECT COUNT(*) FROM attempts WHERE user_id=? AND status='finished' "
                                        "AND practice=0 AND stars=3", (user_id,), 0) >= 1)
    give("both_cases", db.scalar(conn, "SELECT COUNT(DISTINCT case_id) FROM attempts WHERE user_id=? "
                                       "AND status='finished' AND practice=0", (user_id,), 0) >= 2)
    lvl = progress(conn, user_id)["level"]
    give("level_3", lvl >= 3)
    give("level_5", lvl >= 5)
    hours = float(db.scalar(conn, "SELECT SUM(hours) FROM volunteer_shifts WHERE user_id=? AND status='approved'",
                            (user_id,), 0))
    give("volunteer_first", hours > 0)
    give("volunteer_10h", hours >= 10)
    give("note_accepted", db.scalar(conn, "SELECT COUNT(*) FROM field_notes WHERE user_id=? "
                                          "AND status IN ('accepted','converted')", (user_id,), 0) >= 1)
    give("note_converted", db.scalar(conn, "SELECT COUNT(*) FROM field_notes WHERE user_id=? "
                                           "AND status='converted'", (user_id,), 0) >= 1)
    return new
