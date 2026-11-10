"""Раздел преподавателя: группы, назначения, результаты, подтверждение волонтёрских смен."""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db, gamification, security, services

bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _my_groups():
    if g.user["role"] == "admin":
        return db.rows(g.db, "SELECT * FROM groups_ ORDER BY name")
    return db.rows(g.db, "SELECT * FROM groups_ WHERE teacher_id=? ORDER BY name", (g.user["id"],))


def _group_or_404(gid: int):
    grp = db.one(g.db, "SELECT * FROM groups_ WHERE id=?", (gid,))
    if grp is None or (g.user["role"] != "admin" and grp["teacher_id"] != g.user["id"]):
        abort(404)
    return grp


@bp.route("/")
@security.login_required("teacher")
def home():
    groups = []
    for grp in _my_groups():
        n = db.scalar(g.db, "SELECT COUNT(*) FROM users WHERE group_id=? AND role='student' AND is_active=1",
                      (grp["id"],), 0)
        avg = db.scalar(g.db, """SELECT AVG(a.score_pct) FROM attempts a JOIN users u ON u.id=a.user_id
                                 WHERE u.group_id=? AND a.status='finished' AND a.practice=0""", (grp["id"],))
        groups.append({"g": grp, "n": n, "avg": avg})
    pending = db.scalar(g.db, """SELECT COUNT(*) FROM volunteer_shifts s JOIN users u ON u.id=s.user_id
                                 JOIN groups_ gr ON gr.id=u.group_id WHERE gr.teacher_id=? AND s.status='pending'""",
                        (g.user["id"],), 0)
    return render_template("teacher/home.html", groups=groups, pending=pending)


@bp.route("/group/<int:gid>")
@security.login_required("teacher", "admin")
def group(gid):
    grp = _group_or_404(gid)
    students = db.rows(g.db, """
        SELECT u.id, u.full_name, u.login,
          (SELECT COUNT(*) FROM attempts a WHERE a.user_id=u.id AND a.status='finished' AND a.practice=0) done,
          (SELECT AVG(a.score_pct) FROM attempts a WHERE a.user_id=u.id AND a.status='finished' AND a.practice=0) avg,
          COALESCE((SELECT SUM(xp) FROM xp_events x WHERE x.user_id=u.id),0) xp,
          COALESCE((SELECT SUM(hours) FROM volunteer_shifts s WHERE s.user_id=u.id AND s.status='approved'),0) hours
        FROM users u WHERE u.group_id=? AND u.role='student' AND u.is_active=1 ORDER BY u.full_name""", (gid,))
    cases = services.visible_cases(g.db)
    assigned = db.rows(g.db, """SELECT a.*, c.title FROM assignments a JOIN cases c ON c.id=a.case_id
                                WHERE a.group_id=? ORDER BY a.created_at DESC""", (gid,))
    matrix = {}
    for r in db.rows(g.db, """SELECT a.user_id, a.case_id, MAX(a.score_pct) p FROM attempts a JOIN users u ON u.id=a.user_id
                              WHERE u.group_id=? AND a.status='finished' AND a.practice=0
                              GROUP BY a.user_id, a.case_id""", (gid,)):
        matrix[(r["user_id"], r["case_id"])] = r["p"]
    return render_template("teacher/group.html", grp=grp, students=students, cases=cases, assigned=assigned,
                           matrix=matrix)


@bp.route("/group/<int:gid>/assign", methods=["POST"])
@security.login_required("teacher", "admin")
def assign(gid):
    _group_or_404(gid)
    cid = request.form.get("case_id", type=int)
    due = request.form.get("due_at", "").strip() or None
    if not cid or not db.one(g.db, "SELECT 1 FROM cases WHERE id=? AND status='published'", (cid,)):
        flash("Выберите опубликованный кейс.", "error")
    elif db.one(g.db, "SELECT 1 FROM assignments WHERE group_id=? AND case_id=?", (gid, cid)):
        flash("Этот кейс уже назначен группе.", "warn")
    else:
        aid = db.insert(g.db, "assignments", case_id=cid, group_id=gid, assigned_by=g.user["id"], due_at=due,
                        created_at=db.now())
        db.audit(g.db, g.user["id"], "assign", "assignment", aid)
        flash("Кейс назначен группе.", "ok")
    return redirect(url_for("teacher.group", gid=gid))


@bp.route("/group/<int:gid>/unassign/<int:aid>", methods=["POST"])
@security.login_required("teacher", "admin")
def unassign(gid, aid):
    _group_or_404(gid)
    g.db.execute("DELETE FROM assignments WHERE id=? AND group_id=?", (aid, gid))
    flash("Назначение снято.", "ok")
    return redirect(url_for("teacher.group", gid=gid))


@bp.route("/student/<int:uid>")
@security.login_required("teacher", "admin")
def student(uid):
    if not services.can_view_user(g.db, g.user, uid):
        abort(404)
    stu = db.one(g.db, "SELECT u.*, gr.name group_name FROM users u LEFT JOIN groups_ gr ON gr.id=u.group_id "
                       "WHERE u.id=? AND u.role='student'", (uid,))
    if stu is None:
        abort(404)
    attempts = db.rows(g.db, """SELECT a.*, c.title FROM attempts a JOIN cases c ON c.id=a.case_id
                                WHERE a.user_id=? AND a.status='finished' ORDER BY a.finished_at DESC""", (uid,))
    shifts = db.rows(g.db, "SELECT * FROM volunteer_shifts WHERE user_id=? ORDER BY shift_date DESC", (uid,))
    return render_template("teacher/student.html", stu=stu, attempts=attempts, shifts=shifts,
                           prog=gamification.progress(g.db, uid), competencies=services.competency_profile(g.db, uid))


@bp.route("/shifts")
@security.login_required("teacher")
def shifts():
    rows = db.rows(g.db, """SELECT s.*, u.full_name, gr.name group_name FROM volunteer_shifts s
                            JOIN users u ON u.id=s.user_id JOIN groups_ gr ON gr.id=u.group_id
                            WHERE gr.teacher_id=? ORDER BY (s.status='pending') DESC, s.shift_date DESC LIMIT 100""",
                   (g.user["id"],))
    return render_template("teacher/shifts.html", rows=rows)


@bp.route("/shifts/<int:sid>", methods=["POST"])
@security.login_required("teacher")
def decide_shift(sid):
    s = db.one(g.db, """SELECT s.* FROM volunteer_shifts s JOIN users u ON u.id=s.user_id
                        JOIN groups_ gr ON gr.id=u.group_id WHERE s.id=? AND gr.teacher_id=?""", (sid, g.user["id"]))
    if s is None:
        abort(404)
    if s["status"] != "pending":
        flash("Смена уже обработана.", "warn")
        return redirect(url_for("teacher.shifts"))
    decision = request.form.get("decision")
    comment = request.form.get("comment", "").strip()
    if decision == "approve":
        xp = gamification.volunteer_xp(float(s["hours"]))
        g.db.execute("UPDATE volunteer_shifts SET status='approved', confirmed_by=?, confirm_comment=?, xp_awarded=? "
                     "WHERE id=?", (g.user["id"], comment, xp, sid))
        gamification.add_xp(g.db, s["user_id"], "volunteer", sid, xp, f"Волонтёрская смена {s['shift_date']}")
        gamification.check_badges(g.db, s["user_id"])
        flash(f"Смена подтверждена (+{xp} XP студенту).", "ok")
    elif decision == "reject":
        if not comment:
            flash("При отклонении укажите причину.", "error")
            return redirect(url_for("teacher.shifts"))
        g.db.execute("UPDATE volunteer_shifts SET status='rejected', confirmed_by=?, confirm_comment=? WHERE id=?",
                     (g.user["id"], comment, sid))
        flash("Смена отклонена.", "ok")
    db.audit(g.db, g.user["id"], f"shift_{decision}", "shift", sid)
    return redirect(url_for("teacher.shifts"))
