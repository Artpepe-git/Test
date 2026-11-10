"""УчительPRO — локальное приложение (Flask + SQLite)."""
from __future__ import annotations

import secrets
from pathlib import Path

from flask import Flask, abort, g, render_template, request, session

from . import config, db, gamification, security, seed, services


def create_app(data_dir: str | Path | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__)
    ddir = config.prepare_data_dir(Path(data_dir) if data_dir else config.default_data_dir())
    app.config.update(
        DATA_DIR=ddir,
        DB_PATH=ddir / "uchitelpro.db",
        TESTING=testing,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    key_file = ddir / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    app.secret_key = key_file.read_text(encoding="utf-8").strip()

    conn = db.connect(app.config["DB_PATH"])
    db.init_schema(conn)
    seed.run(conn)
    conn.close()

    @app.before_request
    def _open_db():
        g.db = db.connect(app.config["DB_PATH"])
        security.load_user()
        if request.method == "POST":
            token = session.get("csrf")
            if not token or token != request.form.get("_csrf"):
                abort(400, "Сессия формы устарела. Обновите страницу и повторите действие.")

    @app.teardown_request
    def _close_db(_exc):
        conn_ = g.pop("db", None)
        if conn_ is not None:
            conn_.close()

    @app.context_processor
    def _ctx():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        prog = None
        if g.get("user") is not None and g.user["role"] == "student":
            prog = gamification.progress(g.db, g.user["id"])
        return {
            "csrf_token": session["csrf"],
            "ROLE_TITLES": security.ROLE_TITLES,
            "APP_NAME": config.APP_NAME,
            "APP_VERSION": config.APP_VERSION,
            "prog": prog,
            "asset_title": services.asset_title,
            "asset_url": lambda kind, name, mood=None: services.asset_url(app.config["DATA_DIR"], kind, name, mood),
        }

    @app.template_filter("pct")
    def _pct(v):
        return "—" if v is None else f"{round(float(v) * 100)}%"

    @app.template_filter("dt")
    def _dt(v):
        if not v:
            return "—"
        s = str(v)
        return f"{s[8:10]}.{s[5:7]}.{s[0:4]} {s[11:16]}".strip()

    @app.template_filter("d")
    def _d(v):
        if not v:
            return "—"
        s = str(v)
        return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"

    from .routers import admin, auth, common, methodist, mk, student, teacher

    for mod in (auth, common, student, teacher, methodist, admin, mk):
        app.register_blueprint(mod.bp)

    @app.errorhandler(403)
    def _403(_e):
        return render_template("error.html", code=403, title="Нет доступа",
                               text="У вашей роли нет прав на эту страницу."), 403

    @app.errorhandler(404)
    def _404(_e):
        return render_template("error.html", code=404, title="Не найдено",
                               text="Такой страницы или записи нет."), 404

    @app.errorhandler(400)
    def _400(e):
        return render_template("error.html", code=400, title="Запрос отклонён",
                               text=getattr(e, "description", "Некорректный запрос.")), 400

    return app
