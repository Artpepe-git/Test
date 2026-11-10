from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from .. import db, security

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    if g.user is None:
        return redirect(url_for("auth.login"))
    return redirect(security.role_home(g.user["role"]))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(security.role_home(g.user["role"]))
    if request.method == "POST":
        login_ = request.form.get("login", "").strip().lower()
        pwd = request.form.get("password", "")
        if security.login_blocked(login_):
            flash("Слишком много неудачных попыток. Подождите 5 минут.", "error")
            return render_template("login.html"), 429
        user = db.one(g.db, "SELECT * FROM users WHERE lower(login)=? AND is_active=1", (login_,))
        if user is None or not security.verify_password(pwd, user["password_hash"]):
            security.register_fail(login_)
            flash("Неверный логин или пароль.", "error")
            return render_template("login.html"), 401
        security.clear_fails(login_)
        session.clear()
        session["uid"] = user["id"]
        db.audit(g.db, user["id"], "login")
        nxt = request.args.get("next", "")
        if user["must_change"]:
            return redirect(url_for("auth.password"))
        if nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(security.role_home(user["role"]))
    demo = db.scalar(g.db, "SELECT COUNT(*) FROM users WHERE is_demo=1 AND is_active=1", (), 0) > 0
    return render_template("login.html", demo=demo)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@security.login_required()
def password():
    if request.method == "POST":
        old = request.form.get("old", "")
        new = request.form.get("new", "")
        again = request.form.get("again", "")
        if not security.verify_password(old, g.user["password_hash"]):
            flash("Текущий пароль указан неверно.", "error")
        elif new != again:
            flash("Новые пароли не совпадают.", "error")
        elif (problem := security.password_problem(new)):
            flash(problem, "error")
        elif new == old:
            flash("Новый пароль должен отличаться от текущего.", "error")
        else:
            g.db.execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?",
                         (security.hash_password(new), g.user["id"]))
            db.audit(g.db, g.user["id"], "password_change")
            flash("Пароль изменён.", "ok")
            return redirect(security.role_home(g.user["role"]))
    return render_template("password.html")
