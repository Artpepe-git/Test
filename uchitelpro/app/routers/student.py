"""Раздел студента + прохождение кейсов (доступно всем ролям; не-студенты — только тренировка)."""
from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import db, engine, gamification, security, services

bp = Blueprint("student", __name__)


@bp.route("/student")
@security.login_required("student")
def home():
    uid = g.user["id"]
    assigned = db.rows(g.db, """
        SELECT a.id, a.due_at, c.id case_id, c.title, c.category, c.difficulty,
               (SELECT MAX(score_pct) FROM attempts x WHERE x.user_id=? AND x.case_id=c.id
                AND x.status='finished' AND x.practice=0) best
        FROM assignments a JOIN cases c ON c.id=a.case_id
        WHERE (a.user_id=? OR a.group_id=?) AND c.status='published' ORDER BY a.due_at IS NULL, a.due_at""",
                       (uid, uid, g.user["group_id"] or -1))
    recent = db.rows(g.db, """SELECT a.*, c.title FROM attempts a JOIN cases c ON c.id=a.case_id
                              WHERE a.user_id=? AND a.status='finished' ORDER BY a.finished_at DESC LIMIT 5""", (uid,))
    badges = db.rows(g.db, """SELECT b.* FROM user_badges ub JOIN badges b ON b.code=ub.badge_code
                              WHERE ub.user_id=? ORDER BY ub.awarded_at DESC""", (uid,))
    pending = db.rows(g.db, """SELECT a.*, c.title FROM attempts a JOIN cases c ON c.id=a.case_id
                               WHERE a.user_id=? AND a.status='in_progress'""", (uid,))
    return render_template("student/home.html", assigned=assigned, recent=recent, badges=badges, pending=pending,
                           competencies=services.competency_profile(g.db, uid))


@bp.route("/cases")
@security.login_required()
def cases():
    items = services.visible_cases(g.db)
    best = {}
    if g.user["role"] == "student":
        for r in db.rows(g.db, """SELECT case_id, MAX(score_pct) p, MAX(stars) s FROM attempts
                                  WHERE user_id=? AND status='finished' AND practice=0 GROUP BY case_id""",
                         (g.user["id"],)):
            best[r["case_id"]] = r
    return render_template("student/cases.html", items=items, best=best)


@bp.route("/case/<int:cid>")
@security.login_required()
def case(cid):
    c = db.one(g.db, "SELECT * FROM cases WHERE id=? AND status='published'", (cid,))
    if c is None:
        abort(404)
    graph, _, ana = services.version_bundle(g.db, c["current_version_id"])
    attempts = db.rows(g.db, """SELECT * FROM attempts WHERE user_id=? AND case_id=? ORDER BY started_at DESC LIMIT 10""",
                       (g.user["id"], cid))
    comps = services.comp_titles(g.db)
    return render_template("student/case.html", c=c, attempts=attempts, ana=ana,
                           comps=[(k, comps.get(k, k)) for k in graph["competencies"]])


@bp.route("/case/<int:cid>/start", methods=["POST"])
@security.login_required()
def start(cid):
    c = db.one(g.db, "SELECT * FROM cases WHERE id=? AND status='published'", (cid,))
    if c is None:
        abort(404)
    practice = request.form.get("mode") == "practice" or g.user["role"] != "student"
    aid = services.start_attempt(g.db, g.user["id"], c, practice)
    return redirect(url_for("student.play", aid=aid))


def _own_attempt(aid: int):
    att = db.one(g.db, "SELECT * FROM attempts WHERE id=? AND user_id=?", (aid, g.user["id"]))
    if att is None:
        abort(404)
    return att


@bp.route("/play/<int:aid>")
@security.login_required()
def play(aid):
    att = _own_attempt(aid)
    if att["status"] == "finished":
        return redirect(url_for("common.result", aid=aid))
    graph, eng, cur, st = services.play_state(g.db, att)
    case = db.one(g.db, "SELECT title FROM cases WHERE id=?", (att["case_id"],))
    node = engine.public_node(graph, cur, st, eng)
    steps = services.attempt_steps(g.db, aid)
    last = None
    meters = None
    if att["practice"]:
        meters = engine.meters_view(eng, st) if eng.meters else None
        scene_steps = [x for x in steps if x["choice_id"] != engine.NEXT]
        if scene_steps and steps[-1]["choice_id"] != engine.NEXT:
            s = steps[-1]
            prev_steps = services.step_list(g.db, aid)[:-1]
            pn, pst = eng.replay(prev_steps)
            ch = engine.find_choice(graph, s["node_id"], s["choice_id"])
            last = {"rating": eng.rate(pn, pst, ch), "feedback": ch.get("feedback", ""),
                    "text": ch["text"], "titles": engine.RATING_TITLES}
    return render_template("student/play.html", att=att, case=case, node=node, step_no=len(steps) + 1, last=last, meters=meters)


@bp.route("/play/<int:aid>/choose", methods=["POST"])
@security.login_required()
def choose(aid):
    att = _own_attempt(aid)
    try:
        services.make_choice(g.db, att, request.form.get("choice", ""), int(request.form.get("spent", 0) or 0))
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("student.play", aid=aid))


@bp.route("/play/<int:aid>/abandon", methods=["POST"])
@security.login_required()
def abandon(aid):
    att = _own_attempt(aid)
    if att["status"] == "in_progress":
        g.db.execute("DELETE FROM attempts WHERE id=?", (aid,))
        flash("Попытка отменена.", "ok")
    return redirect(url_for("student.cases"))


@bp.route("/profile")
@security.login_required("student")
def profile():
    uid = g.user["id"]
    events = db.rows(g.db, "SELECT * FROM xp_events WHERE user_id=? ORDER BY created_at DESC, id DESC LIMIT 30", (uid,))
    allb = db.rows(g.db, "SELECT * FROM badges ORDER BY rowid")
    got = {r["badge_code"]: r["awarded_at"] for r in db.rows(g.db, "SELECT * FROM user_badges WHERE user_id=?", (uid,))}
    return render_template("student/profile.html", events=events, badges=allb, got=got,
                           competencies=services.competency_profile(g.db, uid))


# --------------------------------------------------------------------------- волонтёрство
FORMS = ["Школьное мероприятие", "Работа с детьми (кружок, помощь)", "Помощь в организации",
         "Сопровождение группы", "Другое"]


@bp.route("/volunteer", methods=["GET", "POST"])
@security.login_required("student")
def volunteer():
    if request.method == "POST":
        try:
            hours = float(request.form.get("hours", "0").replace(",", "."))
        except ValueError:
            hours = 0
        date_ = request.form.get("shift_date", "")
        place = request.form.get("place", "").strip()
        form = request.form.get("form", "")
        if not (0 < hours <= 12) or len(date_) != 10 or not place or form not in FORMS:
            flash("Проверьте поля: дата, место, форма и часы (от 0,5 до 12).", "error")
        elif date_ > db.now()[:10]:
            flash("Смену нельзя заводить будущей датой.", "error")
        else:
            db.insert(g.db, "volunteer_shifts", user_id=g.user["id"], shift_date=date_, place=place, form=form,
                      hours=hours, description=request.form.get("description", "").strip(), created_at=db.now())
            flash("Смена отправлена на подтверждение преподавателю.", "ok")
            return redirect(url_for("student.volunteer"))
    shifts = db.rows(g.db, "SELECT * FROM volunteer_shifts WHERE user_id=? ORDER BY shift_date DESC, id DESC",
                     (g.user["id"],))
    approved = sum(float(s["hours"]) for s in shifts if s["status"] == "approved")
    return render_template("student/volunteer.html", shifts=shifts, approved=approved, forms=FORMS,
                           today=db.now()[:10])


@bp.route("/notes", methods=["GET", "POST"])
@security.login_required("student")
def notes():
    if request.method == "POST":
        f = {k: request.form.get(k, "").strip() for k in ("situation", "action", "result", "lesson")}
        shift = request.form.get("shift_id") or None
        if shift and not db.one(g.db, "SELECT 1 FROM volunteer_shifts WHERE id=? AND user_id=?",
                                (shift, g.user["id"])):
            shift = None
        if len(f["situation"]) < 20 or len(f["action"]) < 10 or len(f["result"]) < 10:
            flash("Опишите ситуацию (от 20 символов), свои действия и результат (от 10).", "error")
        else:
            db.insert(g.db, "field_notes", user_id=g.user["id"], shift_id=shift, status="submitted",
                      created_at=db.now(), **f)
            flash("Заметка отправлена методисту.", "ok")
            return redirect(url_for("student.notes"))
    items = db.rows(g.db, "SELECT * FROM field_notes WHERE user_id=? ORDER BY id DESC", (g.user["id"],))
    shifts = db.rows(g.db, "SELECT id, shift_date, place FROM volunteer_shifts WHERE user_id=? ORDER BY shift_date DESC",
                     (g.user["id"],))
    return render_template("student/notes.html", items=items, shifts=shifts)
