"""Раздел «МК»: сценарии мастер-классов. Доступ задаётся полем roles в app/mk/<slug>.json."""
from __future__ import annotations

import json

from flask import Blueprint, abort, g, render_template, send_from_directory

from .. import config, security

bp = Blueprint("mk", __name__, url_prefix="/mk")


def _all() -> list[dict]:
    out = []
    for path in sorted(config.MK_DIR.glob("*.json")):
        m = json.loads(path.read_text(encoding="utf-8"))
        out.append(m)
    return out


def _visible() -> list[dict]:
    return [m for m in _all() if g.user["role"] in m.get("roles", [])]


def _get(slug: str) -> dict:
    for m in _all():
        if m["slug"] == slug:
            if g.user["role"] not in m.get("roles", []):
                abort(403)
            return m
    abort(404)


@bp.route("/")
@security.login_required()
def index():
    return render_template("mk/index.html", items=_visible())


@bp.route("/<slug>")
@security.login_required()
def show(slug):
    return render_template("mk/show.html", m=_get(slug))


@bp.route("/<slug>/docx")
@security.login_required()
def download(slug):
    m = _get(slug)
    return send_from_directory(config.MK_DIR / "files", m["file"], as_attachment=True,
                               download_name=m["file"])
