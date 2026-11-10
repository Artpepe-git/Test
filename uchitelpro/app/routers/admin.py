"""Раздел администратора: пользователи, группы, контейнеры графики, резервные копии, журнал."""
from __future__ import annotations

import csv
import io
import secrets
import shutil
import sqlite3
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template, request,
                   send_file, url_for)

from .. import config, db, security, services

bp = Blueprint("admin", __name__, url_prefix="/admin")
ROLES = ("student", "teacher", "methodist", "admin")
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def temp_password() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


@bp.route("/")
@security.login_required("admin")
def home():
    counts = {r["role"]: r["n"] for r in db.rows(g.db, "SELECT role, COUNT(*) n FROM users WHERE is_active=1 GROUP BY role")}
    stats = {
        "attempts": db.scalar(g.db, "SELECT COUNT(*) FROM attempts WHERE status='finished' AND practice=0", (), 0),
        "cases": db.scalar(g.db, "SELECT COUNT(*) FROM cases WHERE status='published'", (), 0),
        "shifts": db.scalar(g.db, "SELECT COUNT(*) FROM volunteer_shifts WHERE status='pending'", (), 0),
        "notes": db.scalar(g.db, "SELECT COUNT(*) FROM field_notes WHERE status='submitted'", (), 0),
    }
    demo = db.scalar(g.db, "SELECT COUNT(*) FROM users WHERE is_demo=1 AND is_active=1", (), 0)
    return render_template("admin/home.html", counts=counts, stats=stats, demo=demo)


# --------------------------------------------------------------------------- пользователи
@bp.route("/users")
@security.login_required("admin")
def users():
    rows = db.rows(g.db, """SELECT u.*, gr.name group_name FROM users u LEFT JOIN groups_ gr ON gr.id=u.group_id
                            ORDER BY u.is_active DESC, u.role, u.full_name""")
    groups = db.rows(g.db, "SELECT * FROM groups_ ORDER BY name")
    return render_template("admin/users.html", rows=rows, groups=groups, roles=ROLES)


@bp.route("/users/create", methods=["POST"])
@security.login_required("admin")
def create_user():
    login_ = request.form.get("login", "").strip().lower()
    name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "")
    gid = request.form.get("group_id", type=int)
    if not login_ or not name or role not in ROLES or len(login_) < 3 or " " in login_:
        flash("Укажите логин (от 3 символов, без пробелов), ФИО и роль.", "error")
        return redirect(url_for("admin.users"))
    if db.one(g.db, "SELECT 1 FROM users WHERE lower(login)=?", (login_,)):
        flash("Такой логин уже есть.", "error")
        return redirect(url_for("admin.users"))
    pwd = temp_password()
    uid = db.insert(g.db, "users", login=login_, password_hash=security.hash_password(pwd), full_name=name,
                    role=role, group_id=gid if role == "student" else None, must_change=1, created_at=db.now())
    db.audit(g.db, g.user["id"], "user_create", "user", uid, login_)
    flash(f"Пользователь создан. Временный пароль для «{login_}»: {pwd} (показывается один раз).", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/update", methods=["POST"])
@security.login_required("admin")
def update_user(uid):
    u = db.one(g.db, "SELECT * FROM users WHERE id=?", (uid,))
    if u is None:
        abort(404)
    action = request.form.get("action")
    if action == "reset":
        pwd = temp_password()
        g.db.execute("UPDATE users SET password_hash=?, must_change=1 WHERE id=?", (security.hash_password(pwd), uid))
        db.audit(g.db, g.user["id"], "password_reset", "user", uid)
        flash(f"Новый временный пароль для «{u['login']}»: {pwd} (показывается один раз).", "ok")
    elif action in ("deactivate", "activate"):
        if uid == g.user["id"]:
            flash("Нельзя отключить самого себя.", "error")
        else:
            g.db.execute("UPDATE users SET is_active=? WHERE id=?", (1 if action == "activate" else 0, uid))
            db.audit(g.db, g.user["id"], action, "user", uid)
            flash("Статус учётной записи изменён.", "ok")
    elif action == "profile":
        role = request.form.get("role", u["role"])
        gid = request.form.get("group_id", type=int)
        name = request.form.get("full_name", "").strip() or u["full_name"]
        if role not in ROLES:
            abort(400)
        if uid == g.user["id"] and role != "admin":
            flash("Нельзя снять с себя роль администратора.", "error")
            return redirect(url_for("admin.users"))
        g.db.execute("UPDATE users SET role=?, full_name=?, group_id=? WHERE id=?",
                     (role, name, gid if role == "student" else None, uid))
        db.audit(g.db, g.user["id"], "user_update", "user", uid)
        flash("Данные сохранены.", "ok")
    return redirect(url_for("admin.users"))


@bp.route("/users/import", methods=["POST"])
@security.login_required("admin")
def import_students():
    """Строки вида «ФИО;логин;группа». Пароли выдаются один раз."""
    text = request.form.get("lines", "")
    created, skipped = [], []
    for raw in text.splitlines():
        parts = [p.strip() for p in raw.split(";")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            if raw.strip():
                skipped.append((raw, "нужен формат «ФИО;логин;группа»"))
            continue
        name, login_ = parts[0], parts[1].lower()
        group_name = parts[2] if len(parts) > 2 else ""
        if len(login_) < 3 or " " in login_ or db.one(g.db, "SELECT 1 FROM users WHERE lower(login)=?", (login_,)):
            skipped.append((raw, "логин занят или некорректен"))
            continue
        gid = None
        if group_name:
            row = db.one(g.db, "SELECT id FROM groups_ WHERE name=?", (group_name,))
            gid = row["id"] if row else db.insert(g.db, "groups_", name=group_name, course=1)
        pwd = temp_password()
        db.insert(g.db, "users", login=login_, password_hash=security.hash_password(pwd), full_name=name,
                  role="student", group_id=gid, must_change=1, created_at=db.now())
        created.append((name, login_, group_name, pwd))
    db.audit(g.db, g.user["id"], "import_students", details=f"{len(created)} создано")
    return render_template("admin/import_result.html", created=created, skipped=skipped)


# --------------------------------------------------------------------------- группы
@bp.route("/groups", methods=["GET", "POST"])
@security.login_required("admin")
def groups():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Укажите название группы.", "error")
        elif db.one(g.db, "SELECT 1 FROM groups_ WHERE name=?", (name,)):
            flash("Такая группа уже есть.", "error")
        else:
            db.insert(g.db, "groups_", name=name, course=request.form.get("course", type=int) or 1,
                      teacher_id=request.form.get("teacher_id", type=int))
            flash("Группа создана.", "ok")
        return redirect(url_for("admin.groups"))
    rows = db.rows(g.db, """SELECT gr.*, u.full_name teacher,
                            (SELECT COUNT(*) FROM users s WHERE s.group_id=gr.id AND s.is_active=1) n
                            FROM groups_ gr LEFT JOIN users u ON u.id=gr.teacher_id ORDER BY gr.name""")
    teachers = db.rows(g.db, "SELECT id, full_name FROM users WHERE role='teacher' AND is_active=1 ORDER BY full_name")
    return render_template("admin/groups.html", rows=rows, teachers=teachers)


@bp.route("/groups/<int:gid>/teacher", methods=["POST"])
@security.login_required("admin")
def set_teacher(gid):
    g.db.execute("UPDATE groups_ SET teacher_id=? WHERE id=?", (request.form.get("teacher_id", type=int), gid))
    flash("Куратор группы обновлён.", "ok")
    return redirect(url_for("admin.groups"))


# --------------------------------------------------------------------------- контейнеры графики
@bp.route("/assets", methods=["GET", "POST"])
@security.login_required("admin", "methodist")
def assets():
    data_dir: Path = current_app.config["DATA_DIR"]
    if request.method == "POST":
        kind = request.form.get("kind", "")
        name = request.form.get("name", "")
        f = request.files.get("file")
        ext = Path(f.filename).suffix.lower() if f and f.filename else ""
        if kind not in config.ASSET_KINDS or not name.replace("_", "").isalnum():
            abort(400)
        if ext not in config.ASSET_EXTS:
            flash("Допустимы файлы: " + ", ".join(config.ASSET_EXTS), "error")
        else:
            folder = data_dir / "assets" / kind
            for old in config.ASSET_EXTS:  # заменяем прежний файл слота
                (folder / f"{name}{old}").unlink(missing_ok=True)
            f.save(folder / f"{name}{ext}")
            db.audit(g.db, g.user["id"], "asset_upload", "asset", None, f"{kind}/{name}{ext}")
            flash("Файл загружен в контейнер.", "ok")
        return redirect(url_for("admin.assets"))
    slots = services.asset_slots(g.db, data_dir)
    return render_template("admin/assets.html", slots=slots, folder=str(data_dir / "assets"),
                           kinds=config.ASSET_KINDS)


@bp.route("/assets/delete", methods=["POST"])
@security.login_required("admin", "methodist")
def asset_delete():
    kind, name = request.form.get("kind", ""), request.form.get("name", "")
    if kind not in config.ASSET_KINDS or not name.replace("_", "").isalnum():
        abort(400)
    folder = current_app.config["DATA_DIR"] / "assets" / kind
    for ext in config.ASSET_EXTS:
        (folder / f"{name}{ext}").unlink(missing_ok=True)
    flash("Файл удалён, вернулась заглушка.", "ok")
    return redirect(url_for("admin.assets"))


# --------------------------------------------------------------------------- резервные копии, журнал, экспорт
@bp.route("/backup", methods=["GET", "POST"])
@security.login_required("admin")
def backup():
    bdir: Path = current_app.config["DATA_DIR"] / "backups"
    if request.method == "POST":
        name = "backup_" + db.now().replace(" ", "_").replace(":", "-") + ".db"
        dest = bdir / name
        src = sqlite3.connect(str(current_app.config["DB_PATH"]))
        dst = sqlite3.connect(str(dest))
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        db.audit(g.db, g.user["id"], "backup", details=name)
        flash("Резервная копия создана: " + name, "ok")
        return redirect(url_for("admin.backup"))
    files = sorted(bdir.glob("backup_*.db"), reverse=True)
    items = [{"name": f.name, "size": round(f.stat().st_size / 1024)} for f in files]
    return render_template("admin/backup.html", items=items, folder=str(bdir))


@bp.route("/backup/<name>")
@security.login_required("admin")
def backup_download(name):
    path = current_app.config["DATA_DIR"] / "backups" / Path(name).name
    if not path.is_file() or not path.name.startswith("backup_"):
        abort(404)
    return send_file(path, as_attachment=True)


@bp.route("/audit")
@security.login_required("admin")
def audit():
    rows = db.rows(g.db, """SELECT l.*, u.login FROM audit_log l LEFT JOIN users u ON u.id=l.actor_id
                            ORDER BY l.id DESC LIMIT 200""")
    return render_template("admin/audit.html", rows=rows)


@bp.route("/export/results.csv")
@security.login_required("admin", "teacher", "methodist")
def export_results():
    where, args = "", ()
    if g.user["role"] == "teacher":
        where, args = "AND gr.teacher_id=?", (g.user["id"],)
    rows = db.rows(g.db, f"""SELECT u.full_name, gr.name grp, c.title, a.finished_at, a.outcome, a.earned, a.best_total,
                                    a.score_pct, a.stars, a.xp_awarded
                             FROM attempts a JOIN users u ON u.id=a.user_id JOIN cases c ON c.id=a.case_id
                             LEFT JOIN groups_ gr ON gr.id=u.group_id
                             WHERE a.status='finished' AND a.practice=0 {where} ORDER BY a.finished_at""", args)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ФИО", "Группа", "Кейс", "Завершено", "Исход", "Баллы", "Максимум", "Доля", "Звёзды", "XP"])
    for r in rows:
        w.writerow([r["full_name"], r["grp"] or "", r["title"], r["finished_at"], r["outcome"], r["earned"],
                    r["best_total"], f"{(r['score_pct'] or 0) * 100:.0f}%", r["stars"], r["xp_awarded"]])
    data = io.BytesIO(("﻿" + buf.getvalue()).encode("utf-8"))  # BOM — чтобы Excel открыл кириллицу
    return send_file(data, mimetype="text/csv", as_attachment=True, download_name="results.csv")
