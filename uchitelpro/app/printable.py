"""Печатная версия кейса: бумажная «книга-игра». Один узел графа = одна карточка с номером."""
from __future__ import annotations

import hashlib

from . import engine

MINUS = "−"


def numbering(graph: dict) -> dict[str, int]:
    """Номера карточек: старт всегда №1, остальные перемешаны (по хешу), чтобы номер не подсказывал путь."""
    ids = [i for i in graph["nodes"] if i != graph["start"]]
    ids.sort(key=lambda i: hashlib.sha1((graph.get("start", "") + "|" + i).encode()).hexdigest())
    return {graph["start"]: 1, **{i: n for n, i in enumerate(ids, 2)}}


def sgn(v: int) -> str:
    return ("+" if v > 0 else MINUS if v < 0 else "") + str(abs(v))


def cond_text(c: dict, meters: dict, flags: dict) -> str:
    if "all" in c:
        return " и ".join(_paren(x, meters, flags) for x in c["all"])
    if "any" in c:
        return " или ".join(_paren(x, meters, flags) for x in c["any"])
    if "not" in c:
        inner = c["not"]
        if "flag" in inner:
            return "пометки «%s» нет" % flags.get(inner["flag"], inner["flag"])
        return "не выполнено: " + cond_text(inner, meters, flags)
    if "flag" in c:
        return "в листе есть пометка «%s»" % flags.get(c["flag"], c["flag"])
    if "meter" in c:
        name = "«%s»" % meters.get(c["meter"], c["meter"])
        for key, word in (("gte", "не ниже"), ("lte", "не выше"), ("eq", "ровно")):
            if key in c:
                return "%s %s %s" % (name, word, sgn(c[key]))
    return ""


def _paren(c: dict, meters: dict, flags: dict) -> str:
    t = cond_text(c, meters, flags)
    return "(%s)" % t if ("all" in c or "any" in c) else t


def changes(effects: dict | None, fl: list | None, meters: dict, flags: dict) -> str:
    parts = ["%s %s" % (meters.get(k, k), sgn(v)) for k, v in (effects or {}).items() if v]
    parts += ["пометка «%s»" % flags.get(f, f) for f in (fl or [])]
    return "; ".join(parts)


def build(graph: dict, comps: dict[str, str]) -> dict:
    meters = {m["code"]: m["title"] for m in graph.get("meters") or []}
    flags = {**(graph.get("flag_print") or {}), **(graph.get("flag_titles") or {})}
    num = numbering(graph)
    ratings = engine.choice_ratings(graph)
    cards = []
    for nid, n in graph["nodes"].items():
        kind = engine.node_kind(n)
        card = {"num": num[nid], "id": nid, "kind": kind, "text": n.get("text", ""), "title": n.get("title") or n.get("name") or "",
                "enter": changes(None, n.get("set_flags"), meters, flags), "choices": [], "rules": [], "outcome": n.get("outcome"), "bonus": n.get("bonus", 0)}
        for c in n.get("choices") or []:
            r = ratings.get((nid, c["id"])) or {}
            card["choices"].append({
                "id": c["id"], "text": c["text"], "to": num.get(c["to"]), "changes": changes(c.get("effects"), c.get("flags"), meters, flags),
                "requires": cond_text(c["requires"], meters, flags) if c.get("requires") else "", "hint": c.get("hint", ""),
                "score": sum((c.get("scores") or {}).values()), "scores": c.get("scores") or {}, "feedback": c.get("feedback", ""),
                "rating": "best" if r.get("best") else "good" if r.get("good") else "weak"})
        auto = n.get("auto") or []
        for i, e in enumerate(auto):
            card["rules"].append({"if": cond_text(e["if"], meters, flags) if e.get("if") else "", "to": num.get(e["to"]),
                                  "changes": changes(e.get("effects"), e.get("flags"), meters, flags), "last": i == len(auto) - 1})
        cards.append(card)
    cards.sort(key=lambda c: c["num"])
    ana = engine.analyze(graph)
    return {"cards": cards, "meters": graph.get("meters") or [], "flags": [t for t in flags.values() if t],
            "golden": [num.get(s["node"]) for s in ana.get("golden_path", [])] + [num.get(ana.get("golden_final"))],
            "best_total": ana.get("best_total"), "comps": comps, "n": len(cards)}
