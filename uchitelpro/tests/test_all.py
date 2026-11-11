"""Тесты УчительPRO. Запуск:  python -m unittest discover -s tests -v"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db, engine, gamification, security  # noqa: E402
from app.config import CASES_DIR  # noqa: E402
from app.seed import graph_of  # noqa: E402


def load_case(name: str) -> dict:
    return json.loads((CASES_DIR / name).read_text(encoding="utf-8"))


SLUG_FILE = {"conflict-5b": "case_conflict.json", "parent-meeting": "case_parent.json"}


def picks_by(g: dict, policy) -> list[str]:
    """Список нажатий (выборы и «Далее»), которым политика проходит кейс до финала."""
    eng = engine.Engine(g)
    nid, st = eng.start()
    out = []
    while not engine.is_final(g["nodes"][nid]):
        cid = engine.NEXT if engine.node_kind(g["nodes"][nid]) == "cut" else policy(eng, nid, st)
        out.append(cid)
        nid, st, _ = eng.take(nid, st, cid)
    return out


def _open(eng, nid, st):
    return [c for c in eng.nodes[nid]["choices"] if eng.available(c, st)]


BEST = lambda eng, nid, st: eng.best_choice(nid, st)["id"]  # noqa: E731
WORST = lambda eng, nid, st: min(_open(eng, nid, st), key=lambda c: eng.choice_value(nid, st, c))["id"]  # noqa: E731
LAST = lambda eng, nid, st: _open(eng, nid, st)[-1]["id"]  # noqa: E731


def golden(slug: str) -> list[str]:
    return picks_by(graph_of(load_case(SLUG_FILE[slug])), BEST)


def worst(slug: str) -> list[str]:
    return picks_by(graph_of(load_case(SLUG_FILE[slug])), WORST)


# --------------------------------------------------------------------------- движок
class EngineTests(unittest.TestCase):
    def setUp(self):
        self.cases = {n: load_case(n) for n in ("case_conflict.json", "case_parent.json")}

    def test_builtin_cases_valid(self):
        for name, d in self.cases.items():
            self.assertEqual(engine.validate(graph_of(d), {"COM", "EMP", "TAC", "ETH", "REF"}), [], name)

    def test_branching_richness(self):
        for name, d in self.cases.items():
            ana = engine.analyze(graph_of(d))
            self.assertGreaterEqual(ana["path_count"], 50, name)
            self.assertGreaterEqual(len(ana["finals"]), 4, name)
            outcomes = {d["nodes"][f]["outcome"] for f in ana["finals"]}
            self.assertEqual(outcomes, {"success", "partial", "fail"}, name)

    def test_golden_paths(self):
        a1 = engine.analyze(graph_of(self.cases["case_conflict.json"]))
        self.assertEqual(a1["best_total"], 41)
        self.assertEqual([(x["node"], x["choice"]) for x in a1["golden_path"]],
                         [("S1", "b"), ("S2b", "a"), ("S3", "a"), ("T_A", "a"), ("T_L", "a"), ("S5", "b"),
                          ("S6", "d"), ("S7", "d")])
        self.assertEqual(a1["golden_final"], "E1")
        self.assertEqual(a1["unreachable_finals"], [])
        a2 = engine.analyze(graph_of(self.cases["case_parent.json"]))
        self.assertEqual(a2["best_total"], 32)
        self.assertEqual(a2["golden_final"], "E_PART")
        self.assertEqual(a2["unreachable_finals"], [])

    def test_best_path_is_really_max_bruteforce(self):
        """Полный перебор всех прохождений через движок совпадает с динамическим расчётом."""
        for d in self.cases.values():
            g = graph_of(d)
            eng = engine.Engine(g)
            totals = []

            def walk(nid, st, acc, depth=0):
                self.assertLess(depth, 40)
                node = g["nodes"][nid]
                kind = engine.node_kind(node)
                if kind == "final":
                    totals.append(acc + int(node.get("bonus", 0)))
                    return
                if kind == "cut":
                    n2, s2, _ = eng.take(nid, st, engine.NEXT)
                    walk(n2, s2, acc, depth + 1)
                    return
                for ch in node["choices"]:
                    if eng.available(ch, st):
                        n2, s2, _ = eng.take(nid, st, ch["id"])
                        walk(n2, s2, acc + engine.choice_total(ch), depth + 1)

            nid, st = eng.start()
            walk(nid, st, 0)
            ana = engine.analyze(g)
            self.assertEqual(max(totals), ana["best_total"])
            self.assertEqual(min(totals), ana["worst_total"])
            self.assertEqual(len(totals), ana["path_count"])

    def test_best_answer_depends_on_state(self):
        """Суть v2: оптимальный выбор в одном и том же узле зависит от накопленного состояния."""
        g = graph_of(self.cases["case_conflict.json"])
        r = engine.choice_ratings(g)
        # общий разговор втроём на перемене: где-то оптимален/приемлем, где-то слаб
        c3 = r[("S3", "c")]
        self.assertGreater(c3["good"] + c3["best"], 0)
        self.assertGreater(c3["weak"], 0)
        # закрытые варианты: «чат» закрыт в части состояний и открыт в других
        e = r[("S5", "e")]
        self.assertGreater(e["locked"], 0)
        self.assertGreater(e["best"] + e["good"] + e["weak"], 0)

    def test_recovery_paths_score_below_golden(self):
        """Путь через ошибки не догоняет идеальный."""
        for fn in ("case_conflict.json", "case_parent.json"):
            g = graph_of(self.cases[fn])
            ana = engine.analyze(g)
            steps = []
            eng = engine.Engine(g)
            nid, st = eng.start()
            total = 0
            for pick in picks_by(g, LAST):
                node = g["nodes"][nid]
                if engine.node_kind(node) == "scene":
                    total += engine.choice_total(engine.find_choice(g, nid, pick))
                steps.append(pick)
                nid, st, _ = eng.take(nid, st, pick)
            total += int(g["nodes"][nid].get("bonus", 0))
            self.assertLess(total, ana["best_total"], fn)

    def test_validate_detects_problems(self):
        g = graph_of(self.cases["case_conflict.json"])
        bad = copy.deepcopy(g)
        bad["nodes"]["S1"]["choices"][0]["to"] = "nope"
        self.assertTrue(any("несуществующий" in e for e in engine.validate(bad)))
        loop = copy.deepcopy(g)  # переход в тот же узел без изменения состояния
        loop["nodes"]["S3"]["choices"][0]["to"] = "S3"
        self.assertTrue(any("Зацикливание" in e for e in engine.validate(loop)))
        orphan = copy.deepcopy(g)
        orphan["nodes"]["lost"] = {"final": True, "outcome": "fail", "text": "x"}
        self.assertTrue(any("недостижим" in e for e in engine.validate(orphan)))
        one = copy.deepcopy(g)
        one["nodes"]["S1"]["choices"] = one["nodes"]["S1"]["choices"][:1]
        self.assertTrue(any("не менее двух" in e for e in engine.validate(one)))
        score = copy.deepcopy(g)
        score["nodes"]["S1"]["choices"][0]["scores"]["COM"] = 99
        self.assertTrue(any("от -5 до 5" in e for e in engine.validate(score)))
        unk = copy.deepcopy(g)
        unk["competencies"].append("ZZZ")
        self.assertTrue(any("ZZZ" in e for e in engine.validate(unk, {"COM", "EMP", "TAC", "ETH", "REF"})))
        meter = copy.deepcopy(g)
        meter["nodes"]["S1"]["choices"][0]["effects"] = {"Q": 1}
        self.assertTrue(any("неизвестной шкалы" in e for e in engine.validate(meter)))
        nohint = copy.deepcopy(g)
        del nohint["nodes"]["S5"]["choices"][4]["hint"]
        self.assertTrue(any("подсказка" in e for e in engine.validate(nohint)))
        ghost = copy.deepcopy(g)
        ghost["nodes"]["S5"]["choices"][4]["requires"] = {"flag": "никогда_не_ставится"}
        self.assertTrue(any("нигде не ставится" in e for e in engine.validate(ghost)))
        deadend = copy.deepcopy(g)
        for c in deadend["nodes"]["S7"]["choices"]:
            c["requires"] = {"flag": "know_chat"}
            c["hint"] = "нужно знать про чат"
        self.assertTrue(any("Тупик" in e for e in engine.validate(deadend)))
        noelse = copy.deepcopy(g)
        noelse["nodes"]["S8"]["auto"][-1]["if"] = {"flag": "know_chat"}
        self.assertTrue(any("запасной" in e for e in engine.validate(noelse)))

    def test_public_node_hides_scores(self):
        g = graph_of(self.cases["case_conflict.json"])
        pub = engine.public_node(g, "S1")
        blob = json.dumps(pub, ensure_ascii=False)
        self.assertNotIn("scores", blob)
        self.assertNotIn("feedback", blob)
        self.assertNotIn("effects", blob)
        # закрытый вариант виден с подсказкой, но без условий
        eng = engine.Engine(g)
        st = eng.initial()
        locked = [c for c in engine.public_node(g, "S5", st, eng)["choices"] if c["locked"]]
        self.assertEqual([c["id"] for c in locked], ["e"])
        self.assertTrue(locked[0]["hint"])
        self.assertNotIn("know_chat", json.dumps(locked, ensure_ascii=False))

    def test_stars(self):
        self.assertEqual(engine.stars_for(1.0, "success"), 3)
        self.assertEqual(engine.stars_for(1.0, "partial"), 2)
        self.assertEqual(engine.stars_for(1.0, "fail"), 1)
        self.assertEqual(engine.stars_for(0.7, "success"), 2)
        self.assertEqual(engine.stars_for(0.1, "success"), 0)

    def test_summarize_golden_gives_full_marks(self):
        g = graph_of(self.cases["case_parent.json"])
        ana = engine.analyze(g)
        eng = engine.Engine(g)
        steps, nid, st = [], *eng.start()
        for pick in picks_by(g, BEST):
            steps.append({"node_id": nid, "choice_id": pick})
            nid, st, _ = eng.take(nid, st, pick)
        s = engine.summarize(g, ana, steps, ana["golden_final"])
        self.assertEqual(s["earned"], ana["best_total"])
        self.assertEqual(s["stars"], 3)
        self.assertEqual(s["counts"], {"best": len(ana["golden_path"]), "good": 0, "weak": 0})
        self.assertEqual(len(s["meters"]), 2)
        self.assertTrue(all(c["pct"] == 100 for c in s["competencies"] if c["max"] > 0))


class GamificationTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(gamification.level_for(0)[0], 1)
        self.assertEqual(gamification.level_for(99)[0], 1)
        self.assertEqual(gamification.level_for(100)[0], 2)
        self.assertEqual(gamification.level_for(300)[0], 3)
        lvl, lo, hi = gamification.level_for(450)
        self.assertEqual((lvl, lo, hi), (3, 300, 600))

    def test_case_xp_scales(self):
        self.assertGreater(gamification.case_xp(1.0, 3), gamification.case_xp(1.0, 1))
        self.assertGreater(gamification.case_xp(1.0, 2), gamification.case_xp(0.2, 2))

    def test_volunteer_xp_capped(self):
        self.assertEqual(gamification.volunteer_xp(2), 30)
        self.assertEqual(gamification.volunteer_xp(12), 90)


# --------------------------------------------------------------------------- приложение
class AppBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name, testing=True)
        self.c = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def tok(self):
        self.c.get("/login")
        with self.c.session_transaction() as s:
            return s["csrf"]

    def login(self, user, pwd, c=None):
        c = c or self.c
        c.get("/login")
        with c.session_transaction() as s:
            t = s["csrf"]
        return c.post("/login", data={"login": user, "password": pwd, "_csrf": t}, follow_redirects=True)

    def post(self, url, data=None, c=None, follow=True):
        c = c or self.c
        with c.session_transaction() as s:
            t = s.get("csrf") or "x"
        d = dict(data or {})
        d["_csrf"] = t
        return c.post(url, data=d, follow_redirects=follow)

    def client_for(self, user, pwd):
        c = self.app.test_client()
        self.login(user, pwd, c)
        return c

    def q(self, sql, args=()):
        conn = db.connect(self.app.config["DB_PATH"])
        try:
            return db.rows(conn, sql, args)
        finally:
            conn.close()

    def uid(self, login):
        return self.q("SELECT id FROM users WHERE login=?", (login,))[0]["id"]

    def case_id(self, slug):
        return self.q("SELECT id FROM cases WHERE slug=?", (slug,))[0]["id"]

    def play_path(self, c, slug, picks, mode="graded"):
        """Проходит кейс по списку выборов, возвращает id попытки."""
        cid = self.case_id(slug)
        r = self.post(f"/case/{cid}/start", {"mode": mode}, c=c, follow=False)
        aid = int(r.headers["Location"].rstrip("/").split("/")[-1])
        for pick in picks:
            r = self.post(f"/play/{aid}/choose", {"choice": pick}, c=c)
            self.assertEqual(r.status_code, 200)
        return aid


class AuthTests(AppBase):
    def test_login_required_and_roles(self):
        self.assertEqual(self.c.get("/student").status_code, 302)
        s = self.client_for("student1", "stud123")
        for url in ("/admin/", "/admin/users", "/methodist/", "/teacher/", "/admin/backup", "/admin/audit"):
            self.assertEqual(s.get(url).status_code, 403, url)
        t = self.client_for("teacher", "teach123")
        for url in ("/admin/users", "/methodist/", "/student"):
            self.assertEqual(t.get(url).status_code, 403, url)
        m = self.client_for("methodist", "method123")
        self.assertEqual(m.get("/methodist/").status_code, 200)
        self.assertEqual(m.get("/admin/users").status_code, 403)

    def test_wrong_password_and_lockout(self):
        security._FAILS.clear()
        for _ in range(5):
            r = self.login("student1", "bad")
            self.assertIn("Неверный", r.get_data(as_text=True))
        r = self.login("student1", "stud123")
        self.assertIn("Слишком много", r.get_data(as_text=True))
        security._FAILS.clear()

    def test_admin_must_change_password(self):
        a = self.client_for("admin", "admin")
        self.assertEqual(a.get("/admin/").status_code, 302)  # принудительно на смену пароля
        r = self.post("/password", {"old": "admin", "new": "newpass1", "again": "newpass1"}, c=a)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(a.get("/admin/").status_code, 200)

    def test_forms_render_real_csrf_token(self):
        """Формы в реальных страницах содержат непустой токен, и по нему POST проходит (как в браузере)."""
        import re
        s = self.client_for("student1", "stud123")
        cid = self.case_id("conflict-5b")
        html = s.get(f"/case/{cid}").get_data(as_text=True)
        tokens = re.findall(r'name="_csrf" value="([^"]*)"', html)
        self.assertTrue(tokens and all(t for t in tokens), tokens)
        r = s.post(f"/case/{cid}/start", data={"_csrf": tokens[0], "mode": "graded"})
        self.assertEqual(r.status_code, 302)

    def test_csrf_enforced(self):
        self.login("student1", "stud123")
        r = self.c.post("/logout", data={})
        self.assertEqual(r.status_code, 400)

    def test_password_hash_not_plain(self):
        h = self.q("SELECT password_hash FROM users WHERE login='student1'")[0][0]
        self.assertTrue(h.startswith("scrypt$"))
        self.assertTrue(security.verify_password("stud123", h))
        self.assertFalse(security.verify_password("x", h))


class CaseFlowTests(AppBase):
    def setUp(self):
        super().setUp()
        self.s = self.client_for("student1", "stud123")

    def test_golden_run_conflict(self):
        aid = self.play_path(self.s, "conflict-5b", golden("conflict-5b"))
        a = self.q("SELECT * FROM attempts WHERE id=?", (aid,))[0]
        self.assertEqual((a["status"], a["outcome"], a["earned"], a["best_total"], a["stars"]),
                         ("finished", "success", 41, 41, 3))
        self.assertGreater(a["xp_awarded"], 0)
        r = self.s.get(f"/result/{aid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Золотой путь", r.get_data(as_text=True))
        badges = {b[0] for b in self.q("SELECT badge_code FROM user_badges WHERE user_id=?", (self.uid("student1"),))}
        self.assertTrue({"first_case", "three_stars"} <= badges)

    def test_bad_run(self):
        aid = self.play_path(self.s, "conflict-5b", worst("conflict-5b"))
        a = self.q("SELECT * FROM attempts WHERE id=?", (aid,))[0]
        self.assertEqual(a["outcome"], "fail")
        self.assertLess(a["earned"], 0)
        self.assertLessEqual(a["stars"], 1)
        self.assertEqual(a["score_pct"], 0)

    def test_every_path_reaches_final(self):
        """Каждое прохождение любого кейса заканчивается финалом (без тупиков и зацикливаний)."""
        for fn in ("case_conflict.json", "case_parent.json"):
            g = graph_of(load_case(fn))
            eng = engine.Engine(g)
            ends = set()

            def walk(nid, st, depth=0):
                self.assertLess(depth, 40)
                node = g["nodes"][nid]
                kind = engine.node_kind(node)
                if kind == "final":
                    ends.add(nid)
                    return
                opts = [engine.NEXT] if kind == "cut" else [c["id"] for c in node["choices"] if eng.available(c, st)]
                self.assertTrue(opts, nid)
                for o in opts:
                    n2, s2, _ = eng.take(nid, st, o)
                    walk(n2, s2, depth + 1)

            walk(*eng.start())
            self.assertEqual(ends, set(engine.analyze(g)["finals"]), fn)

    def test_hidden_state_and_locked_choice(self):
        """Закрытый вариант нельзя выбрать, пока нужное не выяснено; в зачёте шкалы скрыты."""
        g = graph_of(load_case("case_conflict.json"))
        # путь к S5 без знания о чате: Лиза и Артём в раздельных беседах отвечают неудачно
        picks = ["b", "a", "a", "b", "next", "b", "next"]
        cid = self.case_id("conflict-5b")
        r = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=self.s, follow=False)
        aid = int(r.headers["Location"].rstrip("/").split("/")[-1])
        for pick in picks:
            self.post(f"/play/{aid}/choose", {"choice": pick}, c=self.s)
        att = self.q("SELECT * FROM attempts WHERE id=?", (aid,))[0]
        self.assertEqual(att["current_node"], "S5")
        html = self.s.get(f"/play/{aid}").get_data(as_text=True)
        self.assertIn("choice locked", html)
        self.assertIn("за стенами класса", html)
        self.assertNotIn("Доверие Артёма", html)  # шкалы в зачётном режиме скрыты
        n = self.q("SELECT COUNT(*) FROM attempt_steps WHERE attempt_id=?", (aid,))[0][0]
        self.post(f"/play/{aid}/choose", {"choice": "e"}, c=self.s)  # закрытый вариант
        self.assertEqual(self.q("SELECT COUNT(*) FROM attempt_steps WHERE attempt_id=?", (aid,))[0][0], n)
        # результат прохождения показывает скрытые шкалы
        for pick in ("b", "a", "a"):  # S5 b, S6 a (медиация), ...
            self.post(f"/play/{aid}/choose", {"choice": pick}, c=self.s)
        att = self.q("SELECT status, current_node FROM attempts WHERE id=?", (aid,))[0]
        self.assertIn(att["current_node"] if att["status"] == "in_progress" else "done", {"S6h", "S7", "done"})

    def test_same_decisions_different_epilogue(self):
        """Отложенные последствия: один и тот же разговор, но разное сообщение взрослым — разные концовки."""
        good = golden("conflict-5b")
        bad = good[:-1] + ["c"]  # S7: «родителям Артёма: он агрессивен»
        a1 = self.play_path(self.s, "conflict-5b", good)
        a2 = self.play_path(self.s, "conflict-5b", bad)
        f = {r[0]: r[1] for r in self.q("SELECT id, final_node FROM attempts")}
        self.assertEqual((f[a1], f[a2]), ("E1", "E5"))

    def test_repeat_xp_decay_and_daily_limit(self):
        first = self.q("SELECT xp_awarded FROM attempts WHERE id=?",
                       (self.play_path(self.s, "conflict-5b", golden("conflict-5b")),))[0][0]
        second = self.q("SELECT xp_awarded FROM attempts WHERE id=?",
                        (self.play_path(self.s, "conflict-5b", golden("conflict-5b")),))[0][0]
        self.assertEqual(second, round(first * 0.5))
        for _ in range(8):
            self.play_path(self.s, "conflict-5b", golden("conflict-5b"))
        total_case = sum(r[0] for r in self.q("SELECT xp FROM xp_events WHERE user_id=? AND source_type='case'",
                                              (self.uid("student1"),)))
        self.assertLessEqual(total_case, gamification.DAILY_CASE_XP_LIMIT)

    def test_practice_gives_no_xp_and_shows_feedback(self):
        cid = self.case_id("conflict-5b")
        r = self.post(f"/case/{cid}/start", {"mode": "practice"}, c=self.s, follow=False)
        aid = int(r.headers["Location"].rstrip("/").split("/")[-1])
        r = self.post(f"/play/{aid}/choose", {"choice": "a"}, c=self.s)
        html = r.get_data(as_text=True)
        self.assertIn("Предыдущий выбор", html)
        self.assertIn("Доверие Артёма", html)  # в тренировке шкалы видны
        self.assertEqual(self.q("SELECT COUNT(*) FROM xp_events WHERE user_id=?", (self.uid("student1"),))[0][0], 0)

    def test_play_page_does_not_leak_scores(self):
        cid = self.case_id("conflict-5b")
        r = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=self.s, follow=True)
        html = r.get_data(as_text=True)
        self.assertNotIn("Золотой путь", html)
        self.assertNotIn("Доверие Артёма", html)
        self.assertNotIn("feedback", html.lower().replace("предыдущий", ""))
        self.assertIn("Контейнер", html.replace("Фон:", "Контейнер") if "Фон:" in html else html + "Контейнер")

    def test_invalid_choice_rejected_and_other_user_blocked(self):
        cid = self.case_id("conflict-5b")
        r = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=self.s, follow=False)
        aid = int(r.headers["Location"].rstrip("/").split("/")[-1])
        self.post(f"/play/{aid}/choose", {"choice": "zzz"}, c=self.s)
        self.assertEqual(self.q("SELECT COUNT(*) FROM attempt_steps WHERE attempt_id=?", (aid,))[0][0], 0)
        other = self.client_for("student2", "stud123")
        self.assertEqual(other.get(f"/play/{aid}").status_code, 404)
        self.assertEqual(self.post(f"/play/{aid}/choose", {"choice": "a"}, c=other).status_code, 404)

    def test_resume_returns_same_attempt(self):
        cid = self.case_id("conflict-5b")
        r1 = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=self.s, follow=False)
        r2 = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=self.s, follow=False)
        self.assertEqual(r1.headers["Location"], r2.headers["Location"])

    def test_result_access_control(self):
        aid = self.play_path(self.s, "conflict-5b", golden("conflict-5b"))
        self.assertEqual(self.client_for("student2", "stud123").get(f"/result/{aid}").status_code, 404)
        self.assertEqual(self.client_for("teacher", "teach123").get(f"/result/{aid}").status_code, 200)
        self.assertEqual(self.client_for("methodist", "method123").get(f"/result/{aid}").status_code, 200)

    def test_both_cases_badge(self):
        self.play_path(self.s, "conflict-5b", golden("conflict-5b"))
        self.play_path(self.s, "parent-meeting", golden("parent-meeting"))
        badges = {b[0] for b in self.q("SELECT badge_code FROM user_badges WHERE user_id=?", (self.uid("student1"),))}
        self.assertIn("both_cases", badges)

    def test_portfolio_has_code_and_changes(self):
        self.play_path(self.s, "conflict-5b", golden("conflict-5b"))
        h1 = self.s.get("/portfolio").get_data(as_text=True)
        self.assertIn("Контрольный код", h1)
        self.play_path(self.s, "parent-meeting", golden("parent-meeting"))
        h2 = self.s.get("/portfolio").get_data(as_text=True)
        code = lambda h: h.split("Контрольный код:")[1].split("<b>")[1].split("</b>")[0]  # noqa: E731
        self.assertNotEqual(code(h1), code(h2))
        self.assertEqual(self.client_for("student2", "stud123").get(f"/portfolio/{self.uid('student1')}").status_code, 404)


class TeacherFlowTests(AppBase):
    def test_assign_and_student_sees(self):
        t = self.client_for("teacher", "teach123")
        gid = self.q("SELECT id FROM groups_")[0][0]
        cid = self.case_id("parent-meeting")
        self.post(f"/teacher/group/{gid}/assign", {"case_id": cid, "due_at": "2030-01-01"}, c=t)
        s = self.client_for("student1", "stud123")
        self.assertIn("Разговор с родителем", s.get("/student").get_data(as_text=True))
        self.assertEqual(t.get(f"/teacher/group/{gid}").status_code, 200)
        self.assertEqual(t.get(f"/teacher/student/{self.uid('student1')}").status_code, 200)

    def test_foreign_group_hidden(self):
        a = self.client_for("admin", "admin")
        self.post("/password", {"old": "admin", "new": "newpass1", "again": "newpass1"}, c=a)
        self.post("/admin/users/create", {"login": "teach2", "full_name": "Другой", "role": "teacher"}, c=a)
        self.post("/admin/groups", {"name": "ЧУЖАЯ-1", "course": "1"}, c=a)
        gid = self.q("SELECT id FROM groups_ WHERE name='ЧУЖАЯ-1'")[0][0]
        t = self.client_for("teacher", "teach123")
        self.assertEqual(t.get(f"/teacher/group/{gid}").status_code, 404)

    def test_volunteer_cycle(self):
        s = self.client_for("student1", "stud123")
        today = db.now()[:10]
        bad = self.post("/volunteer", {"shift_date": "2999-01-01", "place": "Школа", "form": "Другое", "hours": "2"}, c=s)
        self.assertIn("будущей", bad.get_data(as_text=True))
        self.post("/volunteer", {"shift_date": today, "place": "Школа №5", "form": "Другое", "hours": "3",
                                 "description": "Помогал"}, c=s)
        sid = self.q("SELECT id FROM volunteer_shifts")[0][0]
        # студент не может подтвердить сам
        self.assertEqual(self.post(f"/teacher/shifts/{sid}", {"decision": "approve"}, c=s).status_code, 403)
        t = self.client_for("teacher", "teach123")
        r = self.post(f"/teacher/shifts/{sid}", {"decision": "reject", "comment": ""}, c=t)
        self.assertIn("укажите причину", r.get_data(as_text=True).lower())
        self.post(f"/teacher/shifts/{sid}", {"decision": "approve", "comment": "ок"}, c=t)
        row = self.q("SELECT * FROM volunteer_shifts WHERE id=?", (sid,))[0]
        self.assertEqual((row["status"], row["xp_awarded"]), ("approved", 45))
        self.assertEqual(gamification.total_xp(db.connect(self.app.config["DB_PATH"]), self.uid("student1")), 45)
        # повторное подтверждение не удваивает XP
        self.post(f"/teacher/shifts/{sid}", {"decision": "approve"}, c=t)
        self.assertEqual(self.q("SELECT COUNT(*) FROM xp_events WHERE source_type='volunteer'")[0][0], 1)
        badges = {b[0] for b in self.q("SELECT badge_code FROM user_badges")}
        self.assertIn("volunteer_first", badges)

    def test_teacher_cannot_confirm_other_groups_shift(self):
        s = self.client_for("student2", "stud123")
        self.post("/volunteer", {"shift_date": db.now()[:10], "place": "X", "form": "Другое", "hours": "1"}, c=s)
        sid = self.q("SELECT id FROM volunteer_shifts")[0][0]
        conn = db.connect(self.app.config["DB_PATH"])
        conn.execute("UPDATE groups_ SET teacher_id=NULL")
        conn.close()
        t = self.client_for("teacher", "teach123")
        self.assertEqual(self.post(f"/teacher/shifts/{sid}", {"decision": "approve"}, c=t).status_code, 404)

    def test_csv_export(self):
        s = self.client_for("student1", "stud123")
        self.play_path(s, "conflict-5b", golden("conflict-5b"))
        t = self.client_for("teacher", "teach123")
        r = t.get("/admin/export/results.csv")
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertIn("Студент Первый", text)
        self.assertIn("100%", text)


class MethodistFlowTests(AppBase):
    def setUp(self):
        super().setUp()
        self.m = self.client_for("methodist", "method123")

    def test_difficulty_distribution_and_volunteer_cases(self):
        import collections, glob, json as _j
        from app import engine as _e, seed as _s
        cnt = collections.Counter(r[0] for r in self.q("SELECT difficulty FROM cases"))
        self.assertEqual(dict(cnt), {4: 2, 3: 2, 2: 3, 1: 1})
        for path in sorted(glob.glob("app/cases/case_vol*.json")):
            g = _s.graph_of(_j.load(open(path, encoding="utf-8")))
            self.assertEqual(_e.validate(g, {"COM", "EMP", "TAC", "ETH", "REF"}), [], path)
            a = _e.analyze(g)
            self.assertEqual(a["unreachable_finals"], [], path)
            self.assertEqual(g["nodes"][a["golden_final"]]["outcome"], "success", path)
        g = _s.graph_of(_j.load(open("app/cases/case_vol4.json", encoding="utf-8")))
        eng = _e.Engine(g)
        nid, st = eng.start()
        nid, st, _c = eng.take(nid, st, "b")        # пауза: ребёнку не сказали о передаче
        self.assertEqual(nid, "S2")
        ch = {c["id"]: c for c in g["nodes"]["S2"]["choices"]}
        self.assertFalse(eng.available(ch["b"], st))
        nid, st = eng.start()
        nid, st, _c = eng.take(nid, st, "d")        # честно + выбор
        self.assertTrue(eng.available(ch["b"], st))

    def test_mk_access_by_role(self):
        for role_client, sees_staff in ((self.client_for("student1", "stud123"), False), (self.m, True)):
            page = role_client.get("/mk/").get_data(as_text=True)
            self.assertIn("Академия Супергероев", page)
            self.assertEqual("Как принимать решения" in page, sees_staff)
            self.assertEqual(role_client.get("/mk/superheroes-2class").status_code, 200)
            self.assertEqual(role_client.get("/mk/superheroes-2class/docx").status_code, 200)
            self.assertEqual(role_client.get("/mk/decisions-no-time").status_code, 200 if sees_staff else 403)
            self.assertEqual(role_client.get("/mk/decisions-no-time/docx").status_code, 200 if sees_staff else 403)
        self.assertEqual(self.m.get("/mk/nope").status_code, 404)
        self.assertEqual(self.c.get("/mk/").status_code, 302)

    def test_print_version(self):
        cid = self.q("SELECT id FROM cases WHERE slug='conflict-5b'")[0][0]
        s = self.client_for("student1", "stud123")
        self.assertIn(s.get(f"/methodist/case/{cid}/print").status_code, (302, 403))
        page = self.m.get(f"/methodist/case/{cid}/print").get_data(as_text=True)
        self.assertIn("Как играть", page); self.assertIn("карточка 1", page.replace("карточка&nbsp;", "карточка "))
        self.assertNotIn("talked_first_A", page)            # коды пометок заменены названиями
        key = self.m.get(f"/methodist/case/{cid}/print?part=key").get_data(as_text=True)
        self.assertIn("Ключ преподавателя", key); self.assertIn("лучший", key)
        self.assertNotIn("Ключ преподавателя</h1>", page)
        from app import printable, seed
        import json as _j
        g = seed.graph_of(_j.load(open("app/cases/case_conflict.json", encoding="utf-8")))
        nums = printable.numbering(g)
        self.assertEqual(sorted(nums.values()), list(range(1, len(g["nodes"]) + 1)))
        self.assertEqual(nums[g["start"]], 1)

    def test_inclusion_case_state_logic(self):
        import json as _j
        from app import engine as _e, seed as _s
        g = _s.graph_of(_j.load(open("app/cases/case_inclusion.json", encoding="utf-8")))
        eng = _e.Engine(g)
        def play(picks):
            nid, st = eng.start()
            for cid in picks:
                while g["nodes"][nid].get("kind") == "cut":
                    nid, st, _c = eng.take(nid, st, "next")
                nid, st, _c = eng.take(nid, st, cid)
            while not g["nodes"][nid].get("final"):
                nid, st, _c = eng.take(nid, st, "next")
            return nid
        self.assertEqual(play(["b", "b", "d", "d", "b"]), "E_BEST")      # правило утром открывает вопрос ребёнку
        self.assertEqual(play(["d", "d", "c", "b", "b"]), "E_GOOD")      # два допустимых решения: день хороший, но не идеальный
        self.assertEqual(play(["c", "b", "c", "b", "b"]), "E_FAIL")      # травля при игнорировании, ошибка не признана
        self.assertEqual(play(["c", "b", "c", "b", "c"]), "E_WEAK")      # то же, но извинились
        self.assertEqual(play(["b", "b", "c", "b", "a"]), "E_WEAK")      # хорошие решения, но скрыли итог

    def test_case_delete(self):
        cid = self.q("SELECT id FROM cases WHERE slug='parent-meeting'")[0][0]
        s = self.client_for("student1", "stud123")
        self.assertIn(s.get(f"/methodist/case/{cid}/delete").status_code, (302, 403))
        page = self.m.get(f"/methodist/case/{cid}/delete")
        self.assertEqual(page.status_code, 200)
        self.assertIn("нельзя отменить", page.get_data(as_text=True))
        self.post(f"/methodist/case/{cid}/delete", {}, c=self.m)          # без подтверждения
        self.assertEqual(len(self.q("SELECT id FROM cases WHERE id=?", (cid,))), 1)
        self.post(f"/methodist/case/{cid}/delete", {"confirm": "yes"}, c=self.m)
        self.assertEqual(len(self.q("SELECT id FROM cases WHERE id=?", (cid,))), 0)
        self.assertEqual(len(self.q("SELECT id FROM case_versions WHERE case_id=?", (cid,))), 0)
        from app import seed
        conn = db.connect(self.app.config["DB_PATH"])
        seed.load_builtin_cases(conn); conn.commit(); conn.close()          # перезапуск не возвращает кейс
        self.assertEqual(len(self.q("SELECT id FROM cases WHERE slug='parent-meeting'")), 0)

    def test_builder_api_check(self):
        import json as _j
        g = _j.load(open("app/cases/case_parent.json", encoding="utf-8"))
        g = g.get("graph", g)
        r = self.post("/methodist/api/check", {"graph": _j.dumps(g)}, c=self.m)
        d = r.get_json()
        self.assertEqual(d["errors"], [])
        self.assertGreater(d["ana"]["best_total"], 0)
        g["nodes"][g["start"]]["choices"][0]["to"] = "nope"
        d = self.post("/methodist/api/check", {"graph": _j.dumps(g)}, c=self.m).get_json()
        self.assertTrue(d["errors"])
        s = self.client_for("student1", "stud123")
        self.assertIn(self.post("/methodist/api/check", {"graph": "{}"}, c=s).status_code, (302, 403))

    def test_notes_accept_and_convert(self):
        s = self.client_for("student1", "stud123")
        short = self.post("/notes", {"situation": "коротко", "action": "а", "result": "б"}, c=s)
        self.assertIn("Опишите ситуацию", short.get_data(as_text=True))
        self.post("/notes", {"situation": "Ребёнок отказался работать в паре и ушёл из группы.",
                             "action": "Подошла и предложила выбрать роль.", "result": "Он вернулся и участвовал."}, c=s)
        nid = self.q("SELECT id FROM field_notes")[0][0]
        self.assertEqual(self.post(f"/methodist/notes/{nid}", {"decision": "accept"}, c=s).status_code, 403)
        self.post(f"/methodist/notes/{nid}", {"decision": "accept", "comment": "хорошо"}, c=self.m)
        self.assertEqual(self.q("SELECT status FROM field_notes WHERE id=?", (nid,))[0][0], "accepted")
        r = self.post(f"/methodist/notes/{nid}", {"decision": "convert"}, c=self.m)
        self.assertEqual(self.q("SELECT status FROM field_notes WHERE id=?", (nid,))[0][0], "converted")
        case = self.q("SELECT * FROM cases WHERE source_note_id=?", (nid,))[0]
        self.assertEqual(case["status"], "draft")
        self.assertIn("Конструктор кейса", r.get_data(as_text=True))
        xp = sum(x[0] for x in self.q("SELECT xp FROM xp_events WHERE user_id=?", (self.uid("student1"),)))
        self.assertEqual(xp, gamification.NOTE_ACCEPTED_XP + gamification.NOTE_CONVERTED_XP)
        badges = {b[0] for b in self.q("SELECT badge_code FROM user_badges")}
        self.assertTrue({"note_accepted", "note_converted"} <= badges)

    def test_draft_validate_and_publish(self):
        self.post("/methodist/new", {"title": "Мой кейс", "category": "Тест"}, c=self.m)
        cid = self.q("SELECT id FROM cases WHERE title='Мой кейс'")[0][0]
        draft = self.q("SELECT draft_graph, draft_review FROM cases WHERE id=?", (cid,))[0]
        data = {"title": "Мой кейс", "category": "Тест", "difficulty": "1", "duration_min": "5", "description": "d",
                "graph": draft["draft_graph"], "review": draft["draft_review"]}
        # битый JSON
        r = self.post(f"/methodist/case/{cid}/edit", dict(data, graph="{oops", action="publish"), c=self.m)
        self.assertIn("Ошибка JSON", r.get_data(as_text=True))
        # граф с ошибкой
        g = json.loads(draft["draft_graph"])
        g["nodes"]["n1"]["choices"][0]["to"] = "нет"
        r = self.post(f"/methodist/case/{cid}/edit", dict(data, graph=json.dumps(g), action="publish"), c=self.m)
        self.assertIn("несуществующий", r.get_data(as_text=True))
        self.assertEqual(self.q("SELECT status FROM cases WHERE id=?", (cid,))[0][0], "draft")
        # корректный
        self.post(f"/methodist/case/{cid}/edit", dict(data, action="publish"), c=self.m)
        self.assertEqual(self.q("SELECT status FROM cases WHERE id=?", (cid,))[0][0], "published")
        self.assertEqual(self.q("SELECT COUNT(*) FROM case_versions WHERE case_id=?", (cid,))[0][0], 1)
        s = self.client_for("student1", "stud123")
        self.assertIn("Мой кейс", s.get("/cases").get_data(as_text=True))
        # студент не может открыть редактор
        self.assertEqual(s.get(f"/methodist/case/{cid}/edit").status_code, 403)

    def test_version_isolated_from_edits(self):
        """Идущая попытка остаётся на своей версии кейса после публикации новой."""
        s = self.client_for("student1", "stud123")
        cid = self.case_id("conflict-5b")
        r = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=s, follow=False)
        aid = int(r.headers["Location"].rstrip("/").split("/")[-1])
        v1 = self.q("SELECT version_id FROM attempts WHERE id=?", (aid,))[0][0]
        c = self.q("SELECT * FROM cases WHERE id=?", (cid,))[0]
        v = self.q("SELECT graph, review FROM case_versions WHERE id=?", (v1,))[0]
        g = json.loads(v["graph"])
        g["nodes"]["S1"]["text"] = "ИЗМЕНЁННЫЙ ТЕКСТ"
        self.post(f"/methodist/case/{cid}/edit", {"title": c["title"], "category": c["category"], "difficulty": "2",
                                                  "duration_min": "10", "description": "", "action": "publish",
                                                  "graph": json.dumps(g), "review": v["review"]}, c=self.m)
        self.assertEqual(self.q("SELECT COUNT(*) FROM case_versions WHERE case_id=?", (cid,))[0][0], 2)
        self.assertNotIn("ИЗМЕНЁННЫЙ", s.get(f"/play/{aid}").get_data(as_text=True))
        self.post(f"/play/{aid}/abandon", c=s)
        aid2 = self.play_path(s, "conflict-5b", [])  # новая попытка — уже на новой версии
        self.assertNotEqual(aid, aid2)
        self.assertIn("ИЗМЕНЁННЫЙ", s.get(f"/play/{aid2}").get_data(as_text=True))

    def test_analytics_pages(self):
        s = self.client_for("student1", "stud123")
        self.play_path(s, "conflict-5b", golden("conflict-5b"))
        cid = self.case_id("conflict-5b")
        r = self.m.get(f"/methodist/case/{cid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("17962", r.get_data(as_text=True))


class AdminFlowTests(AppBase):
    def setUp(self):
        super().setUp()
        self.a = self.client_for("admin", "admin")
        self.post("/password", {"old": "admin", "new": "newpass1", "again": "newpass1"}, c=self.a)

    def test_user_lifecycle(self):
        r = self.post("/admin/users/create", {"login": "ivanov", "full_name": "Иванов И.", "role": "student"}, c=self.a)
        self.assertIn("Временный пароль", r.get_data(as_text=True))
        uid = self.uid("ivanov")
        r = self.post(f"/admin/users/{uid}/update", {"action": "reset"}, c=self.a)
        pwd = r.get_data(as_text=True).split("Новый временный пароль для «ivanov»: ")[1].split(" ")[0]
        new = self.app.test_client()
        r = self.login("ivanov", pwd, new)
        self.assertIn("Смена пароля", r.get_data(as_text=True))
        self.post(f"/admin/users/{uid}/update", {"action": "deactivate"}, c=self.a)
        self.assertIn("Неверный", self.login("ivanov", pwd, self.app.test_client()).get_data(as_text=True))
        # дубль логина и самоблокировка
        r = self.post("/admin/users/create", {"login": "ivanov", "full_name": "x", "role": "student"}, c=self.a)
        self.assertIn("уже есть", r.get_data(as_text=True))
        r = self.post(f"/admin/users/{self.uid('admin')}/update", {"action": "deactivate"}, c=self.a)
        self.assertIn("самого себя", r.get_data(as_text=True))

    def test_builtin_assets_shipped(self):
        """Готовая графика персонажей копируется в data/ и заглушка остаётся для тех, у кого картинки нет."""
        for f in ("artem.png", "artem_sad.png", "liza_happy.png", "irina_angry.png", "director.png"):
            self.assertTrue((Path(self.tmp.name) / "assets" / "characters" / f).is_file(), f)
        html = self.a.get("/admin/assets").get_data(as_text=True)
        self.assertIn("Персонаж: Координатор смены", html)      # для него картинки нет — остаётся контейнер
        s = self.client_for("student1", "stud123")
        cid = self.case_id("parent-meeting")
        html = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=s).get_data(as_text=True)
        self.assertIn("/assets/characters/irina", html)

    def test_import_students(self):
        r = self.post("/admin/users/import", {"lines": "Петрова А.А.;petrova;ПО-31\nСидоров;sid;ПО-31\nплохая строка\nИванов;petrova;ПО-31"},
                      c=self.a)
        html = r.get_data(as_text=True)
        self.assertIn("Создано: 2", html)
        self.assertIn("Пропущено: 2", html)
        self.assertEqual(self.q("SELECT COUNT(*) FROM users WHERE group_id=(SELECT id FROM groups_ WHERE name='ПО-31')")[0][0], 2)

    def test_assets_slots_upload_and_fallback(self):
        r = self.a.get("/admin/assets")
        html = r.get_data(as_text=True)
        for needle in ("backgrounds/classroom", "characters/liza", "characters/irina", "ui/mascot", "backgrounds/office"):
            self.assertIn(needle, html)
        png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
               b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x9a\xa0\xa0\x00\x00\x00\x00IEND\xaeB`\x82")
        import io
        with self.a.session_transaction() as s:
            t = s["csrf"]
        r = self.a.post("/admin/assets", data={"_csrf": t, "kind": "characters", "name": "liza",
                                               "file": (io.BytesIO(png), "liza.png")}, content_type="multipart/form-data",
                        follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue((Path(self.tmp.name) / "assets" / "characters" / "liza.png").is_file())
        self.assertEqual(self.a.get("/assets/characters/liza.png").status_code, 200)
        # игра подхватывает файл вместо заглушки
        s = self.client_for("student1", "stud123")
        cid = self.case_id("conflict-5b")
        html = self.post(f"/case/{cid}/start", {"mode": "graded"}, c=s).get_data(as_text=True)
        self.assertIn("/assets/characters/liza", html)
        self.assertIn("/assets/characters/artem_angry", html)  # графика из комплекта на месте
        # запрещённое расширение и обход пути
        with self.a.session_transaction() as s2:
            t = s2["csrf"]
        r = self.a.post("/admin/assets", data={"_csrf": t, "kind": "characters", "name": "x", "file": (io.BytesIO(b"x"), "x.exe")},
                        content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Допустимы", r.get_data(as_text=True))
        self.assertEqual(self.a.get("/assets/characters/../../uchitelpro.db").status_code, 404)
        self.assertEqual(self.a.get("/assets/secret/x.png").status_code, 404)

    def test_backup(self):
        self.post("/admin/backup", c=self.a)
        files = list((Path(self.tmp.name) / "backups").glob("backup_*.db"))
        self.assertEqual(len(files), 1)
        name = files[0].name
        self.assertEqual(self.a.get(f"/admin/backup/{name}").status_code, 200)
        self.assertEqual(self.a.get("/admin/backup/..%2Fuchitelpro.db").status_code, 404)

    def test_groups_and_audit(self):
        self.post("/admin/groups", {"name": "ПО-41", "course": "4"}, c=self.a)
        self.assertEqual(self.q("SELECT COUNT(*) FROM groups_ WHERE name='ПО-41'")[0][0], 1)
        self.assertEqual(self.a.get("/admin/audit").status_code, 200)

    def test_second_start_does_not_duplicate_seed(self):
        app2 = create_app(self.tmp.name, testing=True)
        conn = db.connect(app2.config["DB_PATH"])
        self.assertEqual(db.scalar(conn, "SELECT COUNT(*) FROM cases"), 8)
        self.assertEqual(db.scalar(conn, "SELECT COUNT(*) FROM users"), 5)
        conn.close()


if __name__ == "__main__":
    unittest.main()
