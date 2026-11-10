"""Общие страницы: ассеты, результат попытки, портфолио."""
from __future__ import annotations

from flask import Blueprint, abort, current_app, g, render_template, send_from_directory

from .. import config, db, security, services

bp = Blueprint("common", __name__)


@bp.route("/assets/<kind>/<path:filename>")
def asset(kind, filename):
    if kind not in config.ASSET_KINDS:
        abort(404)
    return send_from_directory(current_app.config["DATA_DIR"] / "assets" / kind, filename)


@bp.route("/result/<int:aid>")
@security.login_required()
def result(aid):
    att = db.one(g.db, """SELECT a.*, c.title, c.category FROM attempts a JOIN cases c ON c.id=a.case_id
                          WHERE a.id=?""", (aid,))
    if att is None or not services.can_view_user(g.db, g.user, att["user_id"]):
        abort(404)
    if att["status"] != "finished":
        abort(404)
    owner = db.one(g.db, "SELECT full_name FROM users WHERE id=?", (att["user_id"],))
    return render_template("result.html", att=att, owner=owner, rep=services.attempt_report(g.db, att),
                           mine=att["user_id"] == g.user["id"])


@bp.route("/portfolio")
@bp.route("/portfolio/<int:uid>")
@security.login_required()
def portfolio(uid=None):
    uid = uid or g.user["id"]
    target = db.one(g.db, "SELECT role FROM users WHERE id=?", (uid,))
    if target is None or not services.can_view_user(g.db, g.user, uid):
        abort(404)
    return render_template("portfolio.html", p=services.portfolio_data(g.db, uid))
