"""Раздел методиста: кейсы (черновик → проверка → публикация), аналитика, полевые заметки."""
from __future__ import annotations

import json

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .. import printable, db, engine, gamification, security, seed, services

bp = Blueprint("methodist", __name__, url_prefix="/methodist")
ROLES = ("methodist", "admin")


def skeleton(title: str, situation: str = "") -> tuple[dict, dict]:
    graph = {
        "start": "n1",
        "competencies": ["COM", "EMP", "TAC", "ETH", "REF"],
        "nodes": {
            "n1": {"scene": "classroom", "characters": [{"id": "student_a", "mood": "neutral"}],
                   "speaker": "Ситуация", "text": situation or "Опишите стартовую ситуацию.",
                   "choices": [
                       {"id": "a", "text": "Вариант А", "to": "f_ok", "scores": {"COM": 2, "EMP": 1},
                        "feedback": "Что произойдёт после этого выбора."},
                       {"id": "b", "text": "Вариант Б", "to": "f_bad", "scores": {"TAC": -1},
                        "feedback": "Что произойдёт после этого выбора."}]},
            "f_ok": {"final": True, "outcome": "success", "scene": "classroom", "title": "Хороший финал",
                     "text": "Опишите итог."},
            "f_bad": {"final": True, "outcome": "fail", "scene": "classroom", "title": "Плохой финал",
                      "text": "Опишите итог."},
        },
    }
    review = {"theory": [{"title": "Принцип", "text": "Кратко объясните, на чём основан правильный выбор."}],
              "node_notes": {"n1": "Комментарий к первой ситуации."},
              "final_notes": {"f_ok": "Почему это хороший итог.", "f_bad": "Почему это плохой итог."},
              "takeaways": ["Главный вывод кейса."]}
    return graph, review


@bp.route("/")
@security.login_required(*ROLES)
def home():
    cases = db.rows(g.db, """
        SELECT c.*, v.version,
          (SELECT COUNT(*) FROM attempts a WHERE a.case_id=c.id AND a.status='finished' AND a.practice=0) n,
          (SELECT AVG(score_pct) FROM attempts a WHERE a.case_id=c.id AND a.status='finished' AND a.practice=0) avg
        FROM cases c LEFT JOIN case_versions v ON v.id=c.current_version_id ORDER BY c.id""")
    notes = db.scalar(g.db, "SELECT COUNT(*) FROM field_notes WHERE status='submitted'", (), 0)
    return render_template("methodist/home.html", cases=cases, notes=notes)


@bp.route("/new", methods=["POST"])
@security.login_required(*ROLES)
def new():
    title = request.form.get("title", "").strip() or "Новый кейс"
    graph, review = skeleton(title)
    cid = db.insert(g.db, "cases", title=title, category=request.form.get("category", "").strip() or "Без категории",
                    difficulty=2, duration_min=10, author_id=g.user["id"], status="draft",
                    draft_graph=json.dumps(graph, ensure_ascii=False, indent=1),
                    draft_review=json.dumps(review, ensure_ascii=False, indent=1),
                    created_at=db.now(), updated_at=db.now())
    flash("Черновик создан.", "ok")
    return redirect(url_for("methodist.edit", cid=cid))


def _case(cid):
    c = db.one(g.db, "SELECT * FROM cases WHERE id=?", (cid,))
    if c is None:
        abort(404)
    return c


@bp.route("/case/<int:cid>")
@security.login_required(*ROLES)
def case(cid):
    c = _case(cid)
    ana = node_stats = None
    if c["current_version_id"]:
        graph, review, ana = services.version_bundle(g.db, c["current_version_id"])
        counts = {}
        for r in db.rows(g.db, """SELECT s.node_id, s.choice_id, COUNT(*) n FROM attempt_steps s
                                  JOIN attempts a ON a.id=s.attempt_id WHERE a.version_id=? AND a.practice=0
                                  GROUP BY s.node_id, s.choice_id""", (c["current_version_id"],)):
            counts[(r["node_id"], r["choice_id"])] = r["n"]
        node_stats = []
        ratings = engine.choice_ratings(graph)
        for nid, node in graph["nodes"].items():
            if engine.node_kind(node) != "scene":
                continue
            total = sum(counts.get((nid, ch["id"]), 0) for ch in node["choices"])
            node_stats.append({"id": nid, "text": node["text"], "total": total, "choices": [
                {"id": ch["id"], "text": ch["text"], "n": counts.get((nid, ch["id"]), 0),
                 "r": ratings.get((nid, ch["id"]), {"best": 0, "good": 0, "weak": 0, "locked": 0}),
                 "points": engine.choice_total(ch), "gated": bool(ch.get("requires"))}
                for ch in node["choices"]]})
        finals = db.rows(g.db, """SELECT final_node, COUNT(*) n, AVG(score_pct) avg FROM attempts
                                  WHERE version_id=? AND status='finished' AND practice=0 GROUP BY final_node""",
                         (c["current_version_id"],))
    else:
        finals = []
    versions = db.rows(g.db, "SELECT id, version, published_at FROM case_versions WHERE case_id=? ORDER BY version DESC",
                       (cid,))
    return render_template("methodist/case.html", c=c, ana=ana, node_stats=node_stats, finals=finals,
                           versions=versions)


@bp.route("/case/<int:cid>/edit", methods=["GET", "POST"])
@security.login_required(*ROLES)
def edit(cid):
    c = _case(cid)
    graph_txt = c["draft_graph"]
    review_txt = c["draft_review"]
    if graph_txt is None and c["current_version_id"]:
        v = db.one(g.db, "SELECT graph, review FROM case_versions WHERE id=?", (c["current_version_id"],))
        graph_txt = json.dumps(json.loads(v["graph"]), ensure_ascii=False, indent=1)
        review_txt = json.dumps(json.loads(v["review"]), ensure_ascii=False, indent=1)
    errors, ana, meta = [], None, {k: c[k] for k in ("title", "category", "difficulty", "duration_min", "description")}
    if request.method == "POST":
        action = request.form.get("action", "save")
        graph_txt = request.form.get("graph", "")
        review_txt = request.form.get("review", "")
        meta = {"title": request.form.get("title", "").strip() or c["title"],
                "category": request.form.get("category", "").strip() or c["category"],
                "difficulty": min(5, max(1, request.form.get("difficulty", type=int) or 1)),
                "duration_min": min(120, max(1, request.form.get("duration_min", type=int) or 10)),
                "description": request.form.get("description", "").strip()}
        graph = review = None
        try:
            graph = json.loads(graph_txt)
            review = json.loads(review_txt or "{}")
        except json.JSONDecodeError as e:
            errors.append(f"Ошибка JSON: {e}")
        if graph is not None:
            codes = {r["code"] for r in db.rows(g.db, "SELECT code FROM competencies")}
            errors += engine.validate(graph, codes)
            if not errors:
                ana = engine.analyze(graph)
        if action == "save":
            g.db.execute("""UPDATE cases SET title=?, category=?, difficulty=?, duration_min=?, description=?,
                            draft_graph=?, draft_review=?, updated_at=? WHERE id=?""",
                         (meta["title"], meta["category"], meta["difficulty"], meta["duration_min"],
                          meta["description"], graph_txt, review_txt, db.now(), cid))
            flash("Черновик сохранён." + (" Есть ошибки — смотрите ниже." if errors else " Ошибок не найдено."),
                  "warn" if errors else "ok")
        elif action == "publish":
            if errors:
                flash("Публикация невозможна: исправьте ошибки.", "error")
            else:
                g.db.execute("""UPDATE cases SET category=?, difficulty=?, duration_min=?, description=?,
                                draft_graph=NULL, draft_review=NULL WHERE id=?""",
                             (meta["category"], meta["difficulty"], meta["duration_min"], meta["description"], cid))
                seed.publish_version(g.db, cid, meta["title"], graph, review)
                db.audit(g.db, g.user["id"], "publish_case", "case", cid)
                flash("Новая версия кейса опубликована.", "ok")
                return redirect(url_for("methodist.case", cid=cid))
    elif graph_txt:
        try:
            graph = json.loads(graph_txt)
            errors = engine.validate(graph)
            if not errors:
                ana = engine.analyze(graph)
        except json.JSONDecodeError as e:
            errors = [f"Ошибка JSON: {e}"]
    return render_template("methodist/edit.html", c=c, graph=graph_txt or "", review=review_txt or "", meta=meta,
                           errors=errors, ana=ana, comps=services.comp_titles(g.db))


@bp.route("/api/check", methods=["POST"])
@security.login_required(*ROLES)
def api_check():
    """Живая проверка графа для конструктора: ошибки и краткий расчёт."""
    try:
        graph = json.loads(request.form.get("graph", ""))
    except json.JSONDecodeError as e:
        return jsonify(errors=[f"Ошибка JSON: {e}"])
    if not isinstance(graph, dict):
        return jsonify(errors=["Граф должен быть объектом."])
    codes = {r["code"] for r in db.rows(g.db, "SELECT code FROM competencies")}
    try:
        errors = engine.validate(graph, codes)
        if errors:
            return jsonify(errors=errors)
        ana = engine.analyze(graph)
    except Exception as e:  # некорректная структура, которую проверка не предусмотрела
        return jsonify(errors=[f"Не удалось проверить кейс: {e}"])
    keep = ("best_total", "worst_total", "path_count", "golden_path", "golden_final", "reachable_finals",
            "unreachable_finals", "states_count")
    return jsonify(errors=[], ana={k: ana[k] for k in keep})


@bp.route("/case/<int:cid>/archive", methods=["POST"])
@security.login_required(*ROLES)
def archive(cid):
    c = _case(cid)
    status = "archived" if c["status"] == "published" else ("published" if c["current_version_id"] else c["status"])
    g.db.execute("UPDATE cases SET status=? WHERE id=?", (status, cid))
    flash("Статус кейса изменён: " + status, "ok")
    return redirect(url_for("methodist.home"))


@bp.route("/case/<int:cid>/print")
@security.login_required("teacher", *ROLES)
def print_case(cid):
    c = _case(cid)
    if not c["current_version_id"]:
        flash("Печать доступна после публикации кейса.", "error")
        return redirect(url_for("methodist.case", cid=cid))
    graph, review, _ana = services.version_bundle(g.db, c["current_version_id"])
    data = printable.build(graph, services.comp_titles(g.db))
    return render_template("methodist/print.html", c=c, d=data, key=request.args.get("part") == "key", review=review)


@bp.route("/case/<int:cid>/delete", methods=["GET", "POST"])
@security.login_required(*ROLES)
def delete(cid):
    c = _case(cid)
    if request.method == "POST":
        if request.form.get("confirm") != "yes":
            return redirect(url_for("methodist.home"))
        if c["slug"]:
            g.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", ("deleted_case:" + c["slug"], db.now()))
        g.db.execute("UPDATE field_notes SET case_id=NULL WHERE case_id=?", (cid,))
        g.db.execute("DELETE FROM attempts WHERE case_id=?", (cid,))
        g.db.execute("DELETE FROM assignments WHERE case_id=?", (cid,))
        g.db.execute("DELETE FROM cases WHERE id=?", (cid,))
        db.audit(g.db, g.user["id"], "case_delete", "case", cid, c["title"])
        flash("Кейс «%s» удалён." % c["title"], "ok")
        return redirect(url_for("methodist.home"))
    n_att = db.scalar(g.db, "SELECT COUNT(*) FROM attempts WHERE case_id=?", (cid,), 0)
    n_stu = db.scalar(g.db, "SELECT COUNT(DISTINCT user_id) FROM attempts WHERE case_id=?", (cid,), 0)
    n_asg = db.scalar(g.db, "SELECT COUNT(*) FROM assignments WHERE case_id=?", (cid,), 0)
    return render_template("methodist/delete.html", c=c, n_att=n_att, n_stu=n_stu, n_asg=n_asg)


# --------------------------------------------------------------------------- заметки
@bp.route("/notes")
@security.login_required(*ROLES)
def notes():
    rows = db.rows(g.db, """SELECT n.*, u.full_name FROM field_notes n JOIN users u ON u.id=n.user_id
                            ORDER BY (n.status='submitted') DESC, n.id DESC LIMIT 100""")
    return render_template("methodist/notes.html", rows=rows)


@bp.route("/notes/<int:nid>", methods=["POST"])
@security.login_required(*ROLES)
def decide_note(nid):
    n = db.one(g.db, "SELECT * FROM field_notes WHERE id=?", (nid,))
    if n is None:
        abort(404)
    decision = request.form.get("decision")
    comment = request.form.get("comment", "").strip()
    if decision == "accept" and n["status"] == "submitted":
        g.db.execute("UPDATE field_notes SET status='accepted', reviewer_comment=? WHERE id=?", (comment, nid))
        gamification.add_xp(g.db, n["user_id"], "note", nid, gamification.NOTE_ACCEPTED_XP, "Заметка принята")
        gamification.check_badges(g.db, n["user_id"])
        flash("Заметка принята.", "ok")
    elif decision == "reject" and n["status"] == "submitted":
        if not comment:
            flash("Укажите причину отклонения.", "error")
        else:
            g.db.execute("UPDATE field_notes SET status='rejected', reviewer_comment=? WHERE id=?", (comment, nid))
            flash("Заметка отклонена.", "ok")
    elif decision == "convert" and n["status"] in ("submitted", "accepted"):
        text = f"{n['situation']}\n\nЧто было сделано: {n['action']}\nРезультат: {n['result']}"
        graph, review = skeleton(n["situation"][:60], n["situation"])
        cid = db.insert(g.db, "cases", title="Кейс по заметке №%d" % nid, category="Из практики", difficulty=2,
                        duration_min=10, description=text, author_id=g.user["id"], status="draft",
                        source_note_id=nid, draft_graph=json.dumps(graph, ensure_ascii=False, indent=1),
                        draft_review=json.dumps(review, ensure_ascii=False, indent=1),
                        created_at=db.now(), updated_at=db.now())
        was_accepted = n["status"] == "accepted"
        g.db.execute("UPDATE field_notes SET status='converted', case_id=?, reviewer_comment=? WHERE id=?",
                     (cid, comment or n["reviewer_comment"], nid))
        gamification.add_xp(g.db, n["user_id"], "note", nid,
                            gamification.NOTE_CONVERTED_XP + (0 if was_accepted else gamification.NOTE_ACCEPTED_XP),
                            "По заметке создан кейс")
        gamification.check_badges(g.db, n["user_id"])
        flash("Создан черновик кейса по заметке.", "ok")
        return redirect(url_for("methodist.edit", cid=cid))
    else:
        flash("Это действие сейчас недоступно.", "warn")
    return redirect(url_for("methodist.notes"))
