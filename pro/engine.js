/* Движок кейсов v2 в браузере: порт app/engine.py (условия, шкалы, флаги, роутеры, оптимум). */
const OUTCOME_TITLES = { success: "Успех", partial: "Частичный результат", fail: "Неудача" };
const RATING_TITLES = { best: "Оптимальный выбор", good: "Приемлемо", weak: "Слабый выбор" };
const GOOD_GAP = 3;
const NEXT = "next";

function nodeKind(n) {
  if (n.final) return "final";
  return (n.kind === "cut" || n.kind === "router") ? n.kind : "scene";
}
function choiceTotal(ch) {
  let s = 0;
  for (const v of Object.values(ch.scores || {})) s += (v | 0);
  return s;
}

class Engine {
  constructor(graph) {
    this.g = graph;
    this.nodes = graph.nodes;
    this.meters = graph.meters || [];
    this.codes = this.meters.map(m => m.code);
    this.idx = {};
    this.codes.forEach((c, i) => { this.idx[c] = i; });
    this.lo = this.meters.map(m => (m.min === undefined ? -3 : m.min | 0));
    this.hi = this.meters.map(m => (m.max === undefined ? 3 : m.max | 0));
    this.memo = new Map();
    this.active = new Set();
  }
  initial() {
    return { m: this.meters.map(m => (m.start === undefined ? 0 : m.start | 0)), f: [] };
  }
  key(nid, st) { return nid + "\u0001" + st.m.join(",") + "\u0001" + st.f.join(","); }

  holds(cond, st) {
    if (cond === null || cond === undefined) return true;
    if (cond.all) return cond.all.every(c => this.holds(c, st));
    if (cond.any) return cond.any.some(c => this.holds(c, st));
    if (cond.not) return !this.holds(cond.not, st);
    if (cond.flag !== undefined) return st.f.indexOf(cond.flag) >= 0;
    const v = st.m[this.idx[cond.meter]];
    if (cond.gte !== undefined) return v >= cond.gte;
    if (cond.lte !== undefined) return v <= cond.lte;
    return v === cond.eq;
  }
  apply(st, effects, flags) {
    const m = st.m.slice();
    for (const [code, d] of Object.entries(effects || {})) {
      const i = this.idx[code];
      m[i] = Math.max(this.lo[i], Math.min(this.hi[i], m[i] + (d | 0)));
    }
    let f = st.f;
    if (flags && flags.length) {
      const s = new Set(f);
      flags.forEach(x => s.add(x));
      f = Array.from(s).sort();
    }
    return { m, f };
  }
  enter(nid, st) { return this.apply(st, null, this.nodes[nid].set_flags); }
  pick(node, st) {
    for (const e of node.auto) if (this.holds(e.if, st)) return e;
    throw new Error("Ни одно условие роутера не сработало.");
  }
  advance(nid, st) {
    st = this.enter(nid, st);
    for (let i = 0; i < 100; i++) {
      const node = this.nodes[nid];
      if (nodeKind(node) !== "router") return [nid, st];
      const e = this.pick(node, st);
      st = this.apply(st, e.effects, e.flags);
      nid = e.to;
      st = this.enter(nid, st);
    }
    throw new Error("Слишком длинная цепочка роутеров.");
  }
  available(ch, st) { return this.holds(ch.requires, st); }

  take(nid, st, choiceId) {
    const node = this.nodes[nid], kind = nodeKind(node);
    if (kind === "scene") {
      const ch = node.choices.find(c => c.id === choiceId);
      if (!ch || !this.available(ch, st)) throw new Error("Такого варианта нет или он пока закрыт.");
      const [nxt, st3] = this.advance(ch.to, this.apply(st, ch.effects, ch.flags));
      return [nxt, st3, ch];
    }
    if (kind === "cut" && choiceId === NEXT) {
      const e = this.pick(node, st);
      const [nxt, st3] = this.advance(e.to, this.apply(st, e.effects, e.flags));
      return [nxt, st3, null];
    }
    throw new Error("Из этого узла нельзя сделать такой шаг.");
  }
  start() { return this.advance(this.g.start, this.initial()); }

  // --- оптимум: [лучшая сумма, худшая сумма, число путей, множество финалов]
  solve(nid, st) {
    const k = this.key(nid, st);
    const hit = this.memo.get(k);
    if (hit) return hit;
    if (this.active.has(k)) throw new Error("Зацикливание в узле " + nid + ".");
    this.active.add(k);
    try {
      const res = this.solveInner(nid, st);
      this.memo.set(k, res);
      return res;
    } finally { this.active.delete(k); }
  }
  solveInner(nid, st) {
    const node = this.nodes[nid], kind = nodeKind(node);
    if (kind === "final") {
      const b = node.bonus | 0;
      return [b, b, 1, new Set([nid])];
    }
    if (kind === "cut") {
      const e = this.pick(node, st);
      const [nxt, st3] = this.advance(e.to, this.apply(st, e.effects, e.flags));
      return this.solve(nxt, st3);
    }
    let best = null, worst = null, cnt = 0, open = false;
    const ends = new Set();
    for (const ch of node.choices) {
      if (!this.available(ch, st)) continue;
      open = true;
      const [nxt, st3] = this.advance(ch.to, this.apply(st, ch.effects, ch.flags));
      const [b, w, c, e] = this.solve(nxt, st3);
      const pts = choiceTotal(ch);
      best = best === null ? b + pts : Math.max(best, b + pts);
      worst = worst === null ? w + pts : Math.min(worst, w + pts);
      cnt += c;
      e.forEach(x => ends.add(x));
    }
    if (!open) throw new Error("Тупик в узле " + nid + ".");
    return [best, worst, cnt, ends];
  }
  bestHere(nid, st) { return this.solve(nid, st)[0]; }
  choiceValue(nid, st, ch) {
    const [nxt, st3] = this.advance(ch.to, this.apply(st, ch.effects, ch.flags));
    return choiceTotal(ch) + this.solve(nxt, st3)[0];
  }
  bestChoice(nid, st) {
    let bv = null, bc = null;
    for (const ch of this.nodes[nid].choices) {
      if (!this.available(ch, st)) continue;
      const v = this.choiceValue(nid, st, ch);
      if (bv === null || v > bv) { bv = v; bc = ch; }
    }
    return bc;
  }
  rate(nid, st, ch) {
    const gap = this.bestHere(nid, st) - this.choiceValue(nid, st, ch);
    if (gap <= 0) return "best";
    return gap <= GOOD_GAP ? "good" : "weak";
  }
}

function analyze(graph, eng) {
  eng = eng || new Engine(graph);
  let [nid, st] = eng.start();
  const [best, worst, paths, ends] = eng.solve(nid, st);
  const byComp = {};
  (graph.competencies || []).forEach(c => { byComp[c] = 0; });
  const golden = [];
  while (nodeKind(graph.nodes[nid]) !== "final") {
    if (nodeKind(graph.nodes[nid]) === "scene") {
      const ch = eng.bestChoice(nid, st);
      golden.push({ node: nid, choice: ch.id });
      for (const [c, v] of Object.entries(ch.scores || {})) byComp[c] = (byComp[c] || 0) + (v | 0);
      [nid, st] = eng.take(nid, st, ch.id);
    } else {
      [nid, st] = eng.take(nid, st, NEXT);
    }
  }
  return { best_total: best, worst_total: worst, path_count: paths,
           golden_path: golden, golden_final: nid, golden_by_comp: byComp,
           reachable_finals: Array.from(ends).sort() };
}

/* Округление «половина к чётному», как round() в Python: проценты совпадают с серверной версией. */
function roundHalfEven(x) {
  const f = Math.floor(x), d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

function starsFor(pct, outcome) {
  if (outcome === "fail") return pct >= 0.25 ? 1 : 0;
  let s = pct >= 0.85 ? 3 : pct >= 0.6 ? 2 : pct >= 0.3 ? 1 : 0;
  if (outcome === "partial") s = Math.min(s, 2);
  return s;
}

/* Итоги по списку шагов [{node_id, choice_id}] — порт summarize(). */
function summarize(graph, ana, steps, finalId, eng) {
  eng = eng || new Engine(graph);
  const comps = graph.competencies || [];
  const byComp = {};
  comps.forEach(c => { byComp[c] = 0; });
  const path = [], trace = [], counts = { best: 0, good: 0, weak: 0 };
  let earned = 0;
  let [nid, st] = eng.start();
  for (const s of steps) {
    const node = graph.nodes[nid];
    if (s.node_id !== nid) throw new Error("История попытки не совпадает с кейсом.");
    if (nodeKind(node) === "scene") {
      const ch = node.choices.find(c => c.id === s.choice_id);
      const rating = eng.rate(nid, st, ch);
      const bestCh = eng.bestChoice(nid, st);
      const pts = choiceTotal(ch);
      earned += pts;
      for (const [c, v] of Object.entries(ch.scores || {})) byComp[c] = (byComp[c] || 0) + (v | 0);
      counts[rating]++;
      const [nxt, st2] = eng.take(nid, st, s.choice_id);
      const after = {};
      eng.codes.forEach((c, i) => { after[c] = st2.m[i]; });
      path.push({ node_id: nid, situation: node.text || "", choice_id: ch.id, choice_text: ch.text,
                  points: pts, rating, feedback: ch.feedback || "",
                  best_id: bestCh.id, best_text: bestCh.text, scores: ch.scores || {},
                  effects: ch.effects || {}, meters_after: after });
      trace.push(after);
      nid = nxt; st = st2;
    } else {
      [nid, st] = eng.take(nid, st, s.choice_id);
    }
  }
  const bonus = graph.nodes[finalId].bonus | 0;
  earned += bonus;
  const bestTotal = ana.best_total || 1;
  const pct = Math.min(Math.max(0, earned) / bestTotal, 1);
  const outcome = graph.nodes[finalId].outcome;
  const compRows = comps.map(c => {
    const mx = ana.golden_by_comp[c] || 0;
    const got = Math.max(0, byComp[c] || 0);
    return { code: c, earned: got, max: mx, pct: mx > 0 ? roundHalfEven(Math.min(got / mx, 1) * 100) : null };
  });
  const flags = Object.entries(graph.flag_titles || {}).sort()
    .filter(([f, t]) => st.f.indexOf(f) >= 0 && t).map(([f, t]) => t);
  return { earned, bonus, best_total: ana.best_total, pct, stars: starsFor(pct, outcome),
           outcome, counts, competencies: compRows, path,
           meters: eng.meters.map((m, i) => ({ code: m.code, title: m.title || m.code,
             value: st.m[i], min: eng.lo[i], max: eng.hi[i] })),
           trace, flags };
}
