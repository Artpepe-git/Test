"""Движок сценариев v2: ветвление с состоянием (шкалы + флаги), закрытыми вариантами и роутерами.

Формат графа кейса:
{
  "meters": [{"code": "A", "title": "Доверие Артёма", "min": -3, "max": 3, "start": 0}],   # необязательно
  "competencies": ["COM", "EMP", ...],
  "start": "S1",
  "nodes": {
    "S1": {                                   # сцена с выбором
      "scene": "classroom", "characters": [{"id": "liza", "mood": "sad"}],
      "speaker": "Ситуация", "text": "...",
      "choices": [{
          "id": "a", "text": "...", "to": "S2",
          "scores": {"COM": 2},               # баллы по компетенциям
          "effects": {"A": -1},               # сдвиг шкал
          "flags": ["know_chat"],             # что запоминается
          "requires": {"flag": "know_chat"},  # условие доступности (иначе вариант виден, но закрыт)
          "hint": "Сначала нужно узнать ...",  # подсказка закрытого варианта
          "feedback": "..."}]},
    "R1": {"kind": "cut", "text": "...", "set_flags": [...],        # сцена без выбора («Далее»)
           "auto": [{"if": {"meter": "A", "gte": 1}, "to": "X"}, {"to": "Y"}]},
    "R2": {"kind": "router", "auto": [...]},                        # невидимый автоматический переход
    "E1": {"final": true, "outcome": "success|partial|fail", "bonus": 10, "title": "...", "text": "..."}
  }
}
Условия: {"flag": "x"}, {"meter": "A", "gte": 1 | "lte": -2 | "eq": 0}, {"all": [...]}, {"any": [...]}, {"not": cond}.
Граф без шкал и флагов (старый формат v1) — частный случай и работает без изменений.
Структурные циклы допустимы, если состояние (шкалы и флаги) не повторяется: лучший путь считается точным перебором состояний (узел, шкалы, флаги).
"""
from __future__ import annotations

from typing import Any

OUTCOMES = ("success", "partial", "fail")
OUTCOME_TITLES = {"success": "Успех", "partial": "Частичный результат", "fail": "Неудача"}
RATING_TITLES = {"best": "Оптимальный выбор", "good": "Приемлемо", "weak": "Слабый выбор"}
GOOD_GAP = 3          # на сколько баллов от оптимума выбор ещё считается «приемлемым»
MAX_STATES = 400_000  # защита от «взрыва» состояний при проверке кейса
NEXT = "next"         # id шага «Далее» в сцене без выбора


class GraphError(Exception):
    pass


def node_kind(node: dict) -> str:
    if node.get("final"):
        return "final"
    k = node.get("kind")
    return k if k in ("cut", "router") else "scene"


def is_final(node: dict) -> bool:
    return bool(node.get("final"))


def choice_total(choice: dict) -> int:
    return sum(int(v) for v in (choice.get("scores") or {}).values())


# --------------------------------------------------------------------------- условия
def _cond_errors(cond: Any, meters: set[str], flags_used: set[str], where: str) -> list[str]:
    if cond is None:
        return []
    if not isinstance(cond, dict) or len(cond) == 0:
        return [f"{where}: условие должно быть объектом."]
    errs: list[str] = []
    if "all" in cond or "any" in cond:
        key = "all" if "all" in cond else "any"
        if not isinstance(cond[key], list) or not cond[key]:
            return [f"{where}: «{key}» требует непустой список условий."]
        for c in cond[key]:
            errs += _cond_errors(c, meters, flags_used, where)
    elif "not" in cond:
        errs += _cond_errors(cond["not"], meters, flags_used, where)
    elif "flag" in cond:
        if not isinstance(cond["flag"], str):
            errs.append(f"{where}: имя флага должно быть строкой.")
        else:
            flags_used.add(cond["flag"])
    elif "meter" in cond:
        if cond["meter"] not in meters:
            errs.append(f"{where}: неизвестная шкала «{cond['meter']}».")
        ops = [k for k in ("gte", "lte", "eq") if k in cond]
        if len(ops) != 1 or not isinstance(cond[ops[0]], int):
            errs.append(f"{where}: для шкалы нужно ровно одно из gte / lte / eq с целым числом.")
    else:
        errs.append(f"{where}: непонятное условие {cond}.")
    return errs


def describe_cond(cond: Any, titles: dict[str, str] | None = None) -> str:
    """Короткое человеческое описание условия (для подсказок и редактора)."""
    titles = titles or {}
    if cond is None:
        return "всегда"
    if "all" in cond:
        return " и ".join(describe_cond(c, titles) for c in cond["all"])
    if "any" in cond:
        return " или ".join(describe_cond(c, titles) for c in cond["any"])
    if "not" in cond:
        return "не (" + describe_cond(cond["not"], titles) + ")"
    if "flag" in cond:
        return f"флаг {cond['flag']}"
    name = titles.get(cond["meter"], cond["meter"])
    if "gte" in cond:
        return f"{name} ≥ {cond['gte']}"
    if "lte" in cond:
        return f"{name} ≤ {cond['lte']}"
    return f"{name} = {cond['eq']}"


# --------------------------------------------------------------------------- проверка
def validate(graph: dict, known_comps: set[str] | None = None) -> list[str]:
    errs: list[str] = []
    nodes = graph.get("nodes") or {}
    start = graph.get("start")
    comps = set(graph.get("competencies") or [])
    meters_def = graph.get("meters") or []
    meters = set()
    for m in meters_def:
        code = m.get("code") if isinstance(m, dict) else None
        if not code or code in meters:
            errs.append("Шкалы: у каждой нужен уникальный code.")
        meters.add(code)
    if not nodes:
        return ["В кейсе нет ни одного узла."]
    if start not in nodes:
        return [f"Стартовый узел «{start}» не найден."]
    if known_comps is not None:
        for c in comps - known_comps:
            errs.append(f"Неизвестная компетенция «{c}».")

    flags_set: set[str] = set()
    flags_used: set[str] = set()
    has_final = False
    for nid, node in nodes.items():
        kind = node_kind(node)
        if kind == "final":
            has_final = True
            if node.get("outcome") not in OUTCOMES:
                errs.append(f"Финал {nid}: outcome должен быть одним из {OUTCOMES}.")
            if node.get("choices") or node.get("auto"):
                errs.append(f"Финал {nid} не должен иметь переходов.")
            b = node.get("bonus", 0)
            if not isinstance(b, int) or isinstance(b, bool) or not 0 <= b <= 30:
                errs.append(f"Финал {nid}: bonus должен быть целым от 0 до 30.")
            continue
        if kind in ("scene", "cut") and not str(node.get("text", "")).strip():
            errs.append(f"Узел {nid}: пустой текст ситуации.")
        for f in node.get("set_flags") or []:
            flags_set.add(f)
        if kind in ("cut", "router"):
            auto = node.get("auto") or []
            if not auto:
                errs.append(f"Узел {nid}: нужен список auto с переходами.")
                continue
            if "if" in auto[-1] and auto[-1]["if"] is not None:
                errs.append(f"Узел {nid}: у последнего перехода в auto не должно быть условия (запасной переход).")
            for i, entry in enumerate(auto):
                if entry.get("to") not in nodes:
                    errs.append(f"Узел {nid}: переход в несуществующий узел «{entry.get('to')}».")
                errs += _cond_errors(entry.get("if"), meters, flags_used, f"Узел {nid}, переход {i + 1}")
                for code in (entry.get("effects") or {}):
                    if code not in meters:
                        errs.append(f"Узел {nid}: сдвиг неизвестной шкалы «{code}».")
                flags_set.update(entry.get("flags") or [])
            continue
        choices = node.get("choices") or []
        if len(choices) < 2:
            errs.append(f"Узел {nid}: нужно не менее двух вариантов ответа.")
        seen: set[str] = set()
        for ch in choices:
            cid = ch.get("id")
            where = f"Узел {nid}/{cid}"
            if not cid or cid in seen or cid == NEXT:
                errs.append(f"Узел {nid}: пустой, повторяющийся или зарезервированный id выбора.")
            seen.add(cid)
            if not str(ch.get("text", "")).strip():
                errs.append(f"{where}: пустой текст выбора.")
            if ch.get("to") not in nodes:
                errs.append(f"{where}: переход в несуществующий узел «{ch.get('to')}».")
            for code, val in (ch.get("scores") or {}).items():
                if comps and code not in comps:
                    errs.append(f"{where}: компетенция «{code}» не объявлена в кейсе.")
                if not isinstance(val, int) or isinstance(val, bool) or not -5 <= val <= 5:
                    errs.append(f"{where}: балл «{code}» должен быть целым от -5 до 5.")
            for code, val in (ch.get("effects") or {}).items():
                if code not in meters:
                    errs.append(f"{where}: сдвиг неизвестной шкалы «{code}».")
                if not isinstance(val, int) or isinstance(val, bool) or not -3 <= val <= 3:
                    errs.append(f"{where}: сдвиг шкалы «{code}» должен быть целым от -3 до 3.")
            flags_set.update(ch.get("flags") or [])
            if ch.get("requires") is not None:
                errs += _cond_errors(ch["requires"], meters, flags_used, where)
                if not str(ch.get("hint", "")).strip():
                    errs.append(f"{where}: у закрытого варианта нужна подсказка hint.")
    if not has_final:
        errs.append("В кейсе нет ни одного финального узла.")
    for f in sorted(flags_used - flags_set):
        errs.append(f"Флаг «{f}» проверяется в условиях, но нигде не ставится.")
    if errs:
        return errs

    # достижимость узлов (на уровне графа; циклы по структуре допустимы, если состояние их разрывает — это проверяет Engine)
    def edges(n: dict) -> list[str]:
        k = node_kind(n)
        if k == "final":
            return []
        if k == "scene":
            return [c["to"] for c in n["choices"]]
        return [e["to"] for e in n["auto"]]

    seen_nodes: set[str] = set()
    todo = [start]
    while todo:
        n = todo.pop()
        if n in seen_nodes:
            continue
        seen_nodes.add(n)
        todo.extend(edges(nodes[n]))
    for nid in nodes:
        if nid not in seen_nodes:
            errs.append(f"Узел {nid} недостижим из старта.")
    if errs:
        return errs
    try:
        Engine(graph).root()
    except GraphError as e:
        errs.append(str(e))
    return errs


# --------------------------------------------------------------------------- движок
class Engine:
    """Состояние = (кортеж значений шкал, frozenset флагов). Все функции чистые."""

    def __init__(self, graph: dict):
        self.g = graph
        self.nodes = graph["nodes"]
        self.meters = graph.get("meters") or []
        self.codes = [m["code"] for m in self.meters]
        self.idx = {c: i for i, c in enumerate(self.codes)}
        self.lo = [int(m.get("min", -3)) for m in self.meters]
        self.hi = [int(m.get("max", 3)) for m in self.meters]
        self._memo: dict = {}
        self._active: set = set()

    # ----- состояние
    def initial(self) -> tuple:
        return (tuple(int(m.get("start", 0)) for m in self.meters), frozenset())

    def holds(self, cond: Any, st: tuple) -> bool:
        if cond is None:
            return True
        if "all" in cond:
            return all(self.holds(c, st) for c in cond["all"])
        if "any" in cond:
            return any(self.holds(c, st) for c in cond["any"])
        if "not" in cond:
            return not self.holds(cond["not"], st)
        if "flag" in cond:
            return cond["flag"] in st[1]
        v = st[0][self.idx[cond["meter"]]]
        if "gte" in cond:
            return v >= cond["gte"]
        if "lte" in cond:
            return v <= cond["lte"]
        return v == cond["eq"]

    def _apply(self, st: tuple, effects: dict | None, flags: list | None) -> tuple:
        meters = list(st[0])
        for code, d in (effects or {}).items():
            i = self.idx[code]
            meters[i] = max(self.lo[i], min(self.hi[i], meters[i] + int(d)))
        fl = st[1] | frozenset(flags or ())
        return (tuple(meters), fl)

    def enter(self, nid: str, st: tuple) -> tuple:
        return self._apply(st, None, self.nodes[nid].get("set_flags"))

    def advance(self, nid: str, st: tuple) -> tuple[str, tuple]:
        """Входит в узел и проходит невидимые роутеры до первой сцены/«Далее»/финала."""
        st = self.enter(nid, st)
        for _ in range(100):
            node = self.nodes[nid]
            if node_kind(node) != "router":
                return nid, st
            entry = self._pick(node, st)
            st = self._apply(st, entry.get("effects"), entry.get("flags"))
            nid = entry["to"]
            st = self.enter(nid, st)
        raise GraphError("Слишком длинная цепочка роутеров.")

    def _pick(self, node: dict, st: tuple) -> dict:
        for entry in node["auto"]:
            if self.holds(entry.get("if"), st):
                return entry
        raise GraphError("Ни одно условие роутера не сработало.")

    def available(self, ch: dict, st: tuple) -> bool:
        return self.holds(ch.get("requires"), st)

    def take(self, nid: str, st: tuple, choice_id: str) -> tuple[str, tuple, dict | None]:
        """Один шаг игрока. Возвращает (следующий узел, новое состояние, выбранный вариант или None для «Далее»)."""
        node = self.nodes[nid]
        kind = node_kind(node)
        if kind == "scene":
            ch = next((c for c in node["choices"] if c["id"] == choice_id), None)
            if ch is None or not self.available(ch, st):
                raise ValueError("Такого варианта нет или он пока закрыт.")
            st2 = self._apply(st, ch.get("effects"), ch.get("flags"))
            nxt, st3 = self.advance(ch["to"], st2)
            return nxt, st3, ch
        if kind == "cut" and choice_id == NEXT:
            entry = self._pick(node, st)
            st2 = self._apply(st, entry.get("effects"), entry.get("flags"))
            nxt, st3 = self.advance(entry["to"], st2)
            return nxt, st3, None
        raise ValueError("Из этого узла нельзя сделать такой шаг.")

    def start(self) -> tuple[str, tuple]:
        return self.advance(self.g["start"], self.initial())

    def replay(self, steps: list[dict]) -> tuple[str, tuple]:
        nid, st = self.start()
        for s in steps:
            if s["node_id"] != nid:
                raise ValueError("История попытки не совпадает с кейсом.")
            nid, st, _ = self.take(nid, st, s["choice_id"])
        return nid, st

    # ----- оптимум (динамическое программирование по состояниям)
    def _solve(self, nid: str, st: tuple) -> tuple:
        """(лучшая сумма, худшая сумма, число путей, множество финалов)"""
        key = (nid, st)
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        if key in self._active:
            raise GraphError(f"Зацикливание: в узле {nid} состояние повторилось. Добавьте флаг или сдвиг шкалы, который разрывает цикл.")
        self._active.add(key)
        try:
            return self._solve_inner(nid, st, key)
        finally:
            self._active.discard(key)

    def _solve_inner(self, nid: str, st: tuple, key: tuple) -> tuple:
        if len(self._memo) > MAX_STATES:
            raise GraphError("Слишком много состояний: упростите кейс (меньше шкал, флагов или слияний).")
        node = self.nodes[nid]
        kind = node_kind(node)
        if kind == "final":
            b = int(node.get("bonus", 0))
            res = (b, b, 1, frozenset([nid]))
        elif kind == "cut":
            entry = self._pick(node, st)
            nxt, st3 = self.advance(entry["to"], self._apply(st, entry.get("effects"), entry.get("flags")))
            res = self._solve(nxt, st3)
        else:
            best = worst = None
            cnt = 0
            ends: set = set()
            any_open = False
            for ch in node["choices"]:
                if not self.available(ch, st):
                    continue
                any_open = True
                nxt, st3 = self.advance(ch["to"], self._apply(st, ch.get("effects"), ch.get("flags")))
                b, w, c, e = self._solve(nxt, st3)
                pts = choice_total(ch)
                best = b + pts if best is None else max(best, b + pts)
                worst = w + pts if worst is None else min(worst, w + pts)
                cnt += c
                ends |= e
            if not any_open:
                raise GraphError(f"Тупик: в узле {nid} при некоторых условиях все варианты закрыты.")
            res = (best, worst, cnt, frozenset(ends))
        self._memo[key] = res
        return res

    def root(self) -> tuple:
        nid, st = self.start()
        return self._solve(nid, st)

    def best_here(self, nid: str, st: tuple) -> int:
        return self._solve(nid, st)[0]

    def choice_value(self, nid: str, st: tuple, ch: dict) -> int:
        nxt, st3 = self.advance(ch["to"], self._apply(st, ch.get("effects"), ch.get("flags")))
        return choice_total(ch) + self._solve(nxt, st3)[0]

    def best_choice(self, nid: str, st: tuple) -> dict:
        best_v, best_c = None, None
        for ch in self.nodes[nid]["choices"]:
            if not self.available(ch, st):
                continue
            v = self.choice_value(nid, st, ch)
            if best_v is None or v > best_v:
                best_v, best_c = v, ch
        return best_c

    def rate(self, nid: str, st: tuple, ch: dict) -> str:
        gap = self.best_here(nid, st) - self.choice_value(nid, st, ch)
        if gap <= 0:
            return "best"
        return "good" if gap <= GOOD_GAP else "weak"


# --------------------------------------------------------------------------- анализ кейса
def analyze(graph: dict, eng: Engine | None = None) -> dict[str, Any]:
    eng = eng or Engine(graph)
    best, worst, paths, ends = eng.root()
    nodes = graph["nodes"]
    golden, by_comp = [], {c: 0 for c in graph.get("competencies") or []}
    nid, st = eng.start()
    while node_kind(nodes[nid]) != "final":
        if node_kind(nodes[nid]) == "scene":
            ch = eng.best_choice(nid, st)
            golden.append({"node": nid, "choice": ch["id"]})
            for code, v in (ch.get("scores") or {}).items():
                by_comp[code] = by_comp.get(code, 0) + int(v)
            nid, st, _ = eng.take(nid, st, ch["id"])
        else:
            nid, st, _ = eng.take(nid, st, NEXT)
    all_finals = sorted(k for k, n in nodes.items() if is_final(n))
    return {
        "best_total": best,
        "worst_total": worst,
        "path_count": paths,
        "golden_path": golden,
        "golden_final": nid,
        "golden_by_comp": by_comp,
        "finals": all_finals,
        "reachable_finals": sorted(ends),
        "unreachable_finals": sorted(set(all_finals) - set(ends)),
        "states_count": len(eng._memo),
        "nodes_count": len(nodes),
        "choices_count": sum(len(n.get("choices", []) or []) for n in nodes.values()),
    }


def choice_ratings(graph: dict) -> dict[tuple[str, str], dict]:
    """По всем достижимым состояниям: для каждого выбора — сколько раз он оптимален/приемлем/слаб/закрыт."""
    eng = Engine(graph)
    out: dict[tuple[str, str], dict] = {}
    seen: set = set()
    stack = [eng.start()]
    while stack:
        nid, st = stack.pop()
        if (nid, st) in seen:
            continue
        seen.add((nid, st))
        node = graph["nodes"][nid]
        kind = node_kind(node)
        if kind == "final":
            continue
        if kind == "cut":
            nxt, st3, _ = eng.take(nid, st, NEXT)
            stack.append((nxt, st3))
            continue
        for ch in node["choices"]:
            row = out.setdefault((nid, ch["id"]), {"best": 0, "good": 0, "weak": 0, "locked": 0})
            if not eng.available(ch, st):
                row["locked"] += 1
                continue
            row[eng.rate(nid, st, ch)] += 1
            nxt, st3, _ = eng.take(nid, st, ch["id"])
            stack.append((nxt, st3))
    return out


def stats_of(ana: dict) -> dict:
    keys = ("best_total", "worst_total", "path_count", "nodes_count", "choices_count")
    return {k: ana[k] for k in keys}


# --------------------------------------------------------------------------- прохождение
def meters_view(eng: Engine, st: tuple) -> list[dict]:
    return [{"code": m["code"], "title": m.get("title", m["code"]), "value": st[0][i],
             "min": eng.lo[i], "max": eng.hi[i]} for i, m in enumerate(eng.meters)]


def public_node(graph: dict, node_id: str, st: tuple | None = None, eng: Engine | None = None) -> dict:
    """Что можно показывать студенту: без баллов, оценок и пояснений. Закрытые варианты видны с подсказкой."""
    node = graph["nodes"][node_id]
    kind = node_kind(node)
    out = {
        "id": node_id, "kind": kind,
        "scene": node.get("scene", "default"),
        "characters": node.get("characters", []),
        "speaker": node.get("speaker", ""),
        "text": node.get("text", ""),
        "final": kind == "final",
    }
    if kind == "final":
        out.update(outcome=node["outcome"], title=node.get("title", ""))
    elif kind == "cut":
        out["choices"] = [{"id": NEXT, "text": node.get("button", "Далее"), "locked": False, "hint": ""}]
    else:
        eng = eng or Engine(graph)
        st = st if st is not None else eng.initial()
        out["choices"] = [{"id": c["id"], "text": c["text"], "locked": not eng.available(c, st),
                           "hint": c.get("hint", "") if not eng.available(c, st) else ""}
                          for c in node["choices"]]
    return out


def find_choice(graph: dict, node_id: str, choice_id: str) -> dict | None:
    node = graph["nodes"].get(node_id)
    if not node or node_kind(node) != "scene":
        return None
    return next((c for c in node["choices"] if c["id"] == choice_id), None)


def stars_for(pct: float, outcome: str) -> int:
    if outcome == "fail":
        return 1 if pct >= 0.25 else 0
    stars = 3 if pct >= 0.85 else 2 if pct >= 0.6 else 1 if pct >= 0.3 else 0
    if outcome == "partial":
        stars = min(stars, 2)
    return stars


def summarize(graph: dict, ana: dict, steps: list[dict], final_id: str, eng: Engine | None = None) -> dict:
    """Итоги по списку шагов [{node_id, choice_id}]: оценка каждого шага в его контексте, шкалы, флаги."""
    eng = eng or Engine(graph)
    nodes = graph["nodes"]
    comps = list(graph.get("competencies") or [])
    by_comp = {c: 0 for c in comps}
    path, trace = [], []
    earned = 0
    counts = {"best": 0, "good": 0, "weak": 0}
    nid, st = eng.start()
    for s in steps:
        node = nodes[nid]
        if s["node_id"] != nid:
            raise ValueError("История попытки не совпадает с кейсом.")
        if node_kind(node) == "scene":
            ch = find_choice(graph, nid, s["choice_id"])
            rating = eng.rate(nid, st, ch)
            best_ch = eng.best_choice(nid, st)
            pts = choice_total(ch)
            earned += pts
            for c, v in (ch.get("scores") or {}).items():
                by_comp[c] = by_comp.get(c, 0) + int(v)
            counts[rating] += 1
            nxt, st2, _ = eng.take(nid, st, s["choice_id"])
            path.append({
                "node_id": nid, "situation": node.get("text", ""), "choice_id": ch["id"], "choice_text": ch["text"],
                "points": pts, "rating": rating, "feedback": ch.get("feedback", ""),
                "best_id": best_ch["id"], "best_text": best_ch["text"], "scores": ch.get("scores", {}),
                "effects": ch.get("effects", {}),
                "meters_after": dict(zip(eng.codes, st2[0])),
            })
            trace.append(dict(zip(eng.codes, st2[0])))
            nid, st = nxt, st2
        else:
            nid, st, _ = eng.take(nid, st, s["choice_id"])
    if nid != final_id:
        raise ValueError("Финал попытки не совпадает с переигровкой.")
    bonus = int(nodes[final_id].get("bonus", 0))
    earned += bonus
    best_total = ana["best_total"] or 1
    pct = min(max(0, earned) / best_total, 1.0)
    outcome = nodes[final_id]["outcome"]
    comp_rows = []
    for c in comps:
        mx = ana["golden_by_comp"].get(c, 0)  # 100 % = столько же баллов, сколько на золотом пути
        got = max(0, by_comp.get(c, 0))
        comp_rows.append({"code": c, "earned": got, "max": mx,
                          "pct": round(min(got / mx, 1.0) * 100) if mx > 0 else None})
    return {
        "earned": earned, "bonus": bonus, "best_total": ana["best_total"], "pct": pct,
        "stars": stars_for(pct, outcome), "outcome": outcome, "counts": counts,
        "competencies": comp_rows, "path": path,
        "meters": meters_view(eng, st), "trace": trace,
        "flags": [t for f, t in sorted((graph.get("flag_titles") or {}).items()) if f in st[1] and t],
    }
