/* Блочный конструктор кейсов УчительPRO: сцены, варианты, баллы, шкалы, флаги, условия — без кода.
   Источник правды — объект graph (тот же JSON, что понимает движок). Форма отправляет его скрытым полем. */
(function () {
  "use strict";
  var root = document.getElementById("builder");
  if (!root) return;
  var gTa = document.getElementById("graph-json"), rTa = document.getElementById("review-json");
  var form = document.getElementById("caseform"), jsonPane = document.getElementById("jsonpane");
  var COMPS = {};
  try { COMPS = JSON.parse(root.dataset.comps || "{}"); } catch (e) { COMPS = {}; }
  var MOODS = [["neutral", "спокойный"], ["angry", "злой"], ["sad", "грустный"], ["happy", "радостный"]];
  var BGS = ["classroom", "classroom_after", "corridor", "office"];
  var CHARS = ["artem", "liza", "irina", "director", "student_a"];
  var KIND_NAME = { scene: "Сцена с выбором", cut: "Пауза «Далее»", router: "Автопереход", final: "Концовка" };
  var graph = null, review = null, sel = null, tab = "scenes", jsonDirty = false, parseError = "";
  var checkTimer = null, lastCheck = null, checkSeq = 0;

  /* ---------- утилиты ---------- */
  function h(tag, a) {
    var e = document.createElement(tag), k, v;
    a = a || {};
    for (k in a) {
      v = a[k];
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.indexOf("on") === 0) e.addEventListener(k.slice(2), v);
      else if (k === "value") e.value = v;
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (var i = 2; i < arguments.length; i++) add(e, arguments[i]);
    if (tag === "textarea") { e.classList.add("auto"); e.addEventListener("input", function () { autosize(e); }); }
    return e;
  }
  function add(e, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(e, x); }); return; }
    e.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
  }
  function autosize(t) { t.style.height = "auto"; t.style.height = Math.max(t.scrollHeight + 2, 44) + "px"; }
  function fitAll() { Array.prototype.forEach.call(root.querySelectorAll("textarea.auto"), autosize); }
  function btn(label, fn, cls) { return h("button", { type: "button", class: "btn sm " + (cls || ""), onclick: fn }, label); }
  function select(opts, value, onchange, cls) {
    var s = h("select", { class: cls || "", onchange: function () { onchange(s.value); } });
    opts.forEach(function (o) { s.appendChild(h("option", { value: o[0] }, o[1])); });
    s.value = value == null ? "" : value;
    return s;
  }
  function field(label, control, hint) {
    return h("label", { class: "bf" }, h("span", { class: "bf-l" }, label), control, hint ? h("span", { class: "bf-h" }, hint) : null);
  }
  function kindOf(n) { return n.final ? "final" : (n.kind === "cut" || n.kind === "router") ? n.kind : "scene"; }
  function ids() { return Object.keys(graph.nodes); }
  function clampInt(v, lo, hi) { v = parseInt(v, 10); if (isNaN(v)) return 0; return Math.max(lo, Math.min(hi, v)); }
  function meters() { return graph.meters || (graph.meters = []); }
  function nameOf(id) {
    var n = graph.nodes[id];
    if (!n) return id ? "«" + id + "»" : "— не выбрано —";
    var nm = n.final ? (n.title || n.name) : n.name;
    if (!nm) nm = (n.text || "").replace(/\s+/g, " ").slice(0, 38) + ((n.text || "").length > 38 ? "…" : "");
    return nm || (n.kind === "router" ? "Автопереход" : id);
  }
  function label(id) { // имя сцены; при совпадении имён добавляем технический id
    var nm = nameOf(id), dup = ids().filter(function (x) { return x !== id && nameOf(x) === nm; }).length;
    return dup ? nm + " (" + id + ")" : nm;
  }
  function nextId(prefix) {
    var i = 1; while (graph.nodes[prefix + i]) i++; return prefix + i;
  }
  function choiceId(node) {
    var used = {}, letters = "abcdefghijklmnopqrstuvwxyz";
    (node.choices || []).forEach(function (c) { used[c.id] = 1; });
    for (var i = 0; i < letters.length; i++) if (!used[letters[i]]) return letters[i];
    return "c" + Date.now();
  }
  function comps() { return graph.competencies && graph.competencies.length ? graph.competencies : Object.keys(COMPS); }

  /* ---------- флаги ---------- */
  function flagTitles() { return graph.flag_titles || (graph.flag_titles = {}); }
  function condFlags(c, out) {
    if (!c) return;
    if (c.all || c.any) (c.all || c.any).forEach(function (x) { condFlags(x, out); });
    else if (c.not) condFlags(c.not, out);
    else if (c.flag) out[c.flag] = 1;
  }
  function allFlags() {
    var set = {}, k;
    for (k in flagTitles()) set[k] = 1;
    ids().forEach(function (id) {
      var n = graph.nodes[id];
      (n.set_flags || []).forEach(function (f) { set[f] = 1; });
      (n.choices || []).forEach(function (c) { (c.flags || []).forEach(function (f) { set[f] = 1; }); condFlags(c.requires, set); });
      (n.auto || []).forEach(function (e) { (e.flags || []).forEach(function (f) { set[f] = 1; }); condFlags(e["if"], set); });
    });
    return Object.keys(set);
  }
  function flagName(code) { return flagTitles()[code] || code; }
  function newFlag() {
    var nm = window.prompt("Как назвать это событие? Например: «Узнали про чат» или «Пообещали тайну».");
    if (!nm || !nm.trim()) return null;
    var i = 1; while (allFlags().indexOf("f" + i) >= 0) i++;
    flagTitles()["f" + i] = nm.trim();
    return "f" + i;
  }
  function flagsEditor(obj, key, title) {
    var wrap = h("div", { class: "chips" });
    function draw() {
      wrap.textContent = "";
      (obj[key] || []).forEach(function (f, i) {
        wrap.appendChild(h("span", { class: "chip" }, flagName(f), h("button", { type: "button", class: "chip-x", title: "Убрать", onclick: function () { obj[key].splice(i, 1); if (!obj[key].length) delete obj[key]; touch(); draw(); } }, "×")));
      });
      var opts = [["", "+ " + title]].concat(allFlags().filter(function (f) { return (obj[key] || []).indexOf(f) < 0; })
        .map(function (f) { return [f, flagName(f)]; })).concat([["__new", "＋ новое событие…"]]);
      var s = select(opts, "", function (v) {
        if (!v) return;
        if (v === "__new") { v = newFlag(); if (!v) { s.value = ""; return; } }
        (obj[key] = obj[key] || []).push(v); touch(); draw();
      }, "chip-add");
      wrap.appendChild(s);
    }
    draw();
    return wrap;
  }

  /* ---------- условия ---------- */
  function leafDefault() {
    var m = meters()[0];
    if (m) return { meter: m.code, gte: 1 };
    var f = allFlags()[0];
    return f ? { flag: f } : null;
  }
  function condNode(c, setSelf, remove, rerender) {
    var box = h("div", { class: "cnode" });
    if (c.all || c.any) {
      var key = c.all ? "all" : "any", arr = c[key];
      box.classList.add("cgroup");
      box.appendChild(h("div", { class: "row" },
        select([["all", "Выполняются все условия:"], ["any", "Выполняется любое из условий:"]], key, function (v) {
          if (v === key) return; c[v] = c[key]; delete c[key]; touch(); rerender();
        }, "inline"),
        btn("Убрать группу", function () { remove(); })));
      arr.forEach(function (child, i) {
        box.appendChild(condNode(child, function (nv) { arr[i] = nv; touch(); }, function () {
          arr.splice(i, 1); if (!arr.length) remove(); else { touch(); rerender(); }
        }, rerender));
      });
      box.appendChild(h("div", { class: "row" },
        btn("+ условие", function () { var l = leafDefault(); if (l) { arr.push(l); touch(); rerender(); } else alert("Сначала заведите шкалу или событие (вкладка «Шкалы и события»)."); }),
        btn("+ группа", function () { var l = leafDefault(); if (l) { arr.push({ all: [l] }); touch(); rerender(); } })));
      return box;
    }
    var type = c.meter != null ? "meter" : c.flag != null ? "flag" : (c.not && c.not.flag != null) ? "noflag" : "raw";
    if (type === "raw") {
      box.appendChild(h("div", { class: "row" }, h("code", { class: "small" }, JSON.stringify(c)), btn("Убрать", remove)));
      box.appendChild(h("div", { class: "small muted" }, "Сложное условие: меняется во вкладке «Для опытных»."));
      return box;
    }
    var row = h("div", { class: "row crow" });
    row.appendChild(select([["meter", "Шкала"], ["flag", "Событие произошло"], ["noflag", "Событие не произошло"]], type, function (v) {
      var m = meters()[0], f = allFlags()[0], nv;
      if (v === "meter") nv = m ? { meter: m.code, gte: 1 } : null; else nv = f ? (v === "flag" ? { flag: f } : { not: { flag: f } }) : null;
      if (!nv) { alert("Для этого условия пока нет ни шкалы, ни события."); rerender(); return; }
      setSelf(nv); rerender();
    }, "inline"));
    if (type === "meter") {
      row.appendChild(select(meters().map(function (m) { return [m.code, m.title || m.code]; }), c.meter, function (v) { c.meter = v; touch(); }, "inline"));
      var op = c.gte != null ? "gte" : c.lte != null ? "lte" : "eq";
      var val = h("input", { type: "number", class: "num", value: String(c[op]), oninput: function () { c[curOp()] = clampInt(val.value, -9, 9); touch(); } });
      var curOp = function () { return c.gte != null ? "gte" : c.lte != null ? "lte" : "eq"; };
      row.appendChild(select([["gte", "не меньше"], ["lte", "не больше"], ["eq", "ровно"]], op, function (v) {
        var x = c[curOp()]; delete c.gte; delete c.lte; delete c.eq; c[v] = x; touch();
      }, "inline"));
      row.appendChild(val);
    } else {
      var inner = type === "flag" ? c : c.not;
      row.appendChild(select(allFlags().map(function (f) { return [f, flagName(f)]; }), inner.flag, function (v) { inner.flag = v; touch(); }, "inline"));
    }
    row.appendChild(btn("×", remove, "x"));
    box.appendChild(row);
    return box;
  }
  function condEditor(obj, key, rerender) {
    var c = obj[key], wrap = h("div", { class: "cond" });
    if (!c) {
      wrap.appendChild(btn("+ добавить условие", function () {
        var l = leafDefault();
        if (!l) { alert("Сначала заведите шкалу или событие (вкладка «Шкалы и события»)."); return; }
        obj[key] = l; touch(); rerender();
      }));
      return wrap;
    }
    wrap.appendChild(condNode(c, function (nv) { obj[key] = nv; touch(); }, function () { delete obj[key]; touch(); rerender(); }, rerender));
    if (!(c.all || c.any)) wrap.appendChild(btn("+ ещё условие", function () {
      var l = leafDefault(); if (l) { obj[key] = { all: [c, l] }; touch(); rerender(); }
    }));
    return wrap;
  }

  /* ---------- состояние и сохранение ---------- */
  function touch() { dirtyDraw(); sync(); scheduleCheck(); }
  var drawTimer = null;
  function dirtyDraw() { clearTimeout(drawTimer); drawTimer = setTimeout(function () { drawSide(); }, 200); }
  function sync() {
    if (!graph) return;
    gTa.value = JSON.stringify(graph, null, 1);
    rTa.value = JSON.stringify(review, null, 1);
    jsonDirty = false;
  }
  function load(gText, rText) {
    try {
      graph = JSON.parse(gText);
      if (!graph || typeof graph !== "object" || !graph.nodes) throw new Error("нет поля nodes");
      review = rText && rText.trim() ? JSON.parse(rText) : {};
    } catch (e) { parseError = String(e.message || e); graph = null; return false; }
    parseError = "";
    review.theory = review.theory || []; review.takeaways = review.takeaways || [];
    review.node_notes = review.node_notes || {}; review.final_notes = review.final_notes || {};
    graph.competencies = graph.competencies && graph.competencies.length ? graph.competencies : Object.keys(COMPS);
    if (!sel || !graph.nodes[sel]) sel = graph.start && graph.nodes[graph.start] ? graph.start : ids()[0];
    return true;
  }

  /* ---------- проверка на сервере ---------- */
  function scheduleCheck() { clearTimeout(checkTimer); setStatus(null, true); checkTimer = setTimeout(runCheck, 700); }
  function runCheck() {
    if (!graph) return;
    var seq = ++checkSeq, fd = new FormData();
    fd.append("_csrf", root.dataset.csrf); fd.append("graph", JSON.stringify(graph));
    fetch(root.dataset.check, { method: "POST", body: fd, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (seq === checkSeq) { lastCheck = d; setStatus(d, false); } })
      .catch(function () { if (seq === checkSeq) setStatus({ errors: ["Не удалось связаться с программой. Она запущена?"] }, false); });
  }
  function humanize(msg) {
    ids().sort(function (a, b) { return b.length - a.length; }).forEach(function (id) {
      if (id.length < 2) return;
      msg = msg.replace(new RegExp("(Узел|Финал) " + id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?![\\w])", "g"), "Сцена «" + label(id) + "»");
      msg = msg.replace(new RegExp("«" + id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "»", "g"), "«" + label(id) + "»");
    });
    return msg.replace(/Сцена «([^»]+)»\/(\w+):/g, "Сцена «$1», вариант $2:").replace(/переход в несуществующий узел «[^»]*»/g, "не выбрана сцена, куда ведёт выбор")
      .replace(/Узел /g, "Сцена ");
  }
  var statusBox = null;
  function setStatus(d, pending) {
    if (!statusBox) return;
    statusBox.className = "bld-status";
    statusBox.textContent = "";
    if (pending || !d) { statusBox.classList.add("pending"); statusBox.textContent = "Проверяю…"; return; }
    if (d.errors && d.errors.length) {
      statusBox.classList.add("err");
      statusBox.appendChild(h("b", {}, "Нужно исправить (" + d.errors.length + "):"));
      statusBox.appendChild(h("ul", {}, d.errors.slice(0, 8).map(function (e) { return h("li", {}, humanize(e)); })));
      if (d.errors.length > 8) statusBox.appendChild(h("div", { class: "small" }, "…и ещё " + (d.errors.length - 8)));
      return;
    }
    var a = d.ana; statusBox.classList.add("ok");
    var path = (a.golden_path || []).map(function (s) { return label(s.node); }).join(" → ");
    statusBox.appendChild(h("div", {}, h("b", {}, "Кейс готов к публикации. "),
      "Лучший результат: ", h("b", {}, a.best_total + " б."), ", худший: " + a.worst_total + ", различных прохождений: " + a.path_count + "."));
    if (a.unreachable_finals && a.unreachable_finals.length)
      statusBox.appendChild(h("div", { class: "warn-line" }, "Недостижимые концовки: " + a.unreachable_finals.map(label).join(", ") + ". Проверьте условия."));
    statusBox.appendChild(h("div", { class: "small muted" }, "Идеальный путь: " + path + " → " + label(a.golden_final)));
  }

  /* ---------- создание и удаление сцен ---------- */
  function newChoice(node) { return { id: choiceId(node), text: "", to: "", scores: {}, feedback: "" }; }
  function newNode(kind) {
    var id = nextId(kind === "final" ? "f" : "s"), n;
    var base = { scene: "classroom", characters: [], speaker: kind === "final" ? "Итог" : "Ситуация", text: "" };
    if (kind === "scene") { n = Object.assign({ name: "Новая сцена" }, base, { choices: [] }); n.choices.push(newChoice(n)); n.choices.push(newChoice(n)); }
    else if (kind === "cut") n = Object.assign({ kind: "cut", name: "Новая пауза" }, base, { auto: [{ to: "" }] });
    else if (kind === "router") n = { kind: "router", name: "Автопереход", auto: [{ to: "" }] };
    else n = Object.assign({ final: true, outcome: "partial", bonus: 0, title: "Новая концовка" }, base);
    graph.nodes[id] = n;
    return id;
  }
  function addAndSelect(kind) { sel = newNode(kind); touch(); drawAll(); jump(); }
  function deleteNode(id) {
    if (!window.confirm("Удалить сцену «" + label(id) + "»? Выборы, которые вели в неё, останутся без цели.")) return;
    delete graph.nodes[id]; delete review.node_notes[id]; delete review.final_notes[id];
    ids().forEach(function (x) {
      var n = graph.nodes[x];
      (n.choices || []).forEach(function (c) { if (c.to === id) c.to = ""; });
      (n.auto || []).forEach(function (e) { if (e.to === id) e.to = ""; });
    });
    if (graph.start === id) graph.start = ids()[0] || "";
    sel = graph.start; touch(); drawAll();
  }
  function jump() { var el = document.getElementById("bld-editor"); if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "start" }); }
  function sceneSelect(value, onchange, allowNone) {
    var opts = [["", "— выберите сцену —"]].concat(ids().map(function (id) { return [id, KIND_NAME[kindOf(graph.nodes[id])].split(" ")[0] + ": " + label(id)]; }));
    return select(opts, value, onchange);
  }
  function targetPicker(obj, key) {
    var wrap = h("div", { class: "row target" });
    var s = sceneSelect(obj[key], function (v) { obj[key] = v; touch(); wrap.classList.toggle("bad", !v); });
    wrap.classList.toggle("bad", !obj[key]);
    wrap.appendChild(s);
    wrap.appendChild(btn("＋ новая сцена", function () { var id = newNode("scene"); obj[key] = id; touch(); drawAll(); }));
    if (obj[key] && graph.nodes[obj[key]]) wrap.appendChild(btn("открыть →", function () { sel = obj[key]; drawAll(); jump(); }));
    return wrap;
  }

  /* ---------- схема переходов ---------- */
  function edgesOf(id) {
    var n = graph.nodes[id], out = [];
    if (n.choices) n.choices.forEach(function (c) { if (graph.nodes[c.to]) out.push({ to: c.to, locked: !!c.requires }); });
    if (n.auto) n.auto.forEach(function (e) { if (graph.nodes[e.to]) out.push({ to: e.to, cond: !!e["if"] }); });
    return out;
  }
  function layout() {
    var all = ids(), depth = {}, state = {}, back = {};
    var start = graph.nodes[graph.start] ? graph.start : all[0];
    (function dfs(u) {
      state[u] = 1;
      edgesOf(u).forEach(function (e) {
        if (state[e.to] === 1) back[u + ">" + e.to] = 1; else if (!state[e.to]) dfs(e.to);
      });
      state[u] = 2;
    })(start);
    all.forEach(function (id) { depth[id] = 0; });
    for (var pass = 0; pass < all.length; pass++) {
      var changed = false;
      all.forEach(function (u) {
        if (!state[u]) return;
        edgesOf(u).forEach(function (e) {
          if (back[u + ">" + e.to] || !state[e.to]) return;
          if (depth[e.to] < depth[u] + 1) { depth[e.to] = depth[u] + 1; changed = true; }
        });
      });
      if (!changed) break;
    }
    var maxD = 0; all.forEach(function (id) { if (state[id]) maxD = Math.max(maxD, depth[id]); });
    all.forEach(function (id) { if (!state[id]) depth[id] = maxD + 1; });
    var cols = {}, pos = {};
    all.forEach(function (id) { (cols[depth[id]] = cols[depth[id]] || []).push(id); });
    var H = 0;
    Object.keys(cols).forEach(function (d) {
      cols[d].forEach(function (id, i) { pos[id] = { x: 24 + d * 210, y: 24 + i * 58 }; H = Math.max(H, 24 + (i + 1) * 58); });
    });
    return { pos: pos, back: back, W: 24 + (Object.keys(cols).length) * 210, H: H + 16 };
  }
  var NS = "http://www.w3.org/2000/svg";
  function svg(tag, a) { var e = document.createElementNS(NS, tag); for (var k in (a || {})) e.setAttribute(k, a[k]); for (var i = 2; i < arguments.length; i++) if (arguments[i]) e.appendChild(arguments[i]); return e; }
  function drawMap(host) {
    host.textContent = "";
    if (!ids().length) return;
    var L = layout(), pos = L.pos, W = 168, Hh = 40;
    var s = svg("svg", { width: L.W, height: L.H, viewBox: "0 0 " + L.W + " " + L.H, role: "img", "aria-label": "Схема сцен и переходов" });
    var defs = svg("defs", {}, svg("marker", { id: "arr", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" }, svg("path", { d: "M0 0L10 5L0 10z", fill: "currentColor" })));
    s.appendChild(defs);
    var gE = svg("g", { fill: "none" }), gN = svg("g", {});
    ids().forEach(function (u) {
      edgesOf(u).forEach(function (e) {
        var a = pos[u], b = pos[e.to], isBack = L.back[u + ">" + e.to], x1 = a.x + W, y1 = a.y + Hh / 2, x2 = b.x, y2 = b.y + Hh / 2, d;
        if (isBack || x2 <= x1) { d = "M" + (a.x + W / 2) + "," + (a.y + Hh) + " C" + (a.x + W / 2) + "," + (a.y + Hh + 40) + " " + (b.x + W / 2) + "," + (b.y + Hh + 40) + " " + (b.x + W / 2) + "," + (b.y + Hh + 3); }
        else { var dx = Math.max(30, (x2 - x1) / 2); d = "M" + x1 + "," + y1 + " C" + (x1 + dx) + "," + y1 + " " + (x2 - dx) + "," + y2 + " " + (x2 - 3) + "," + y2; }
        var hot = (u === sel || e.to === sel);
        gE.appendChild(svg("path", { d: d, class: "edge" + (hot ? " hot" : "") + (e.locked || e.cond || isBack ? " dashed" : ""), "marker-end": "url(#arr)" }));
      });
    });
    ids().forEach(function (id) {
      var n = graph.nodes[id], k = kindOf(n), p = pos[id];
      var cls = "gnode k-" + k + (k === "final" ? " o-" + (n.outcome || "") : "") + (id === sel ? " sel" : "");
      var g = svg("g", { class: cls, transform: "translate(" + p.x + "," + p.y + ")", tabindex: 0, role: "button", "aria-label": label(id) });
      g.appendChild(svg("rect", { width: W, height: Hh, rx: 8 }));
      var lb = (id === graph.start ? "▶ " : "") + label(id), l1 = lb, l2 = "";
      if (lb.length > 24) { var cut = lb.lastIndexOf(" ", 24); if (cut < 10) cut = 24; l1 = lb.slice(0, cut); l2 = lb.slice(cut).trim(); if (l2.length > 24) l2 = l2.slice(0, 23) + "…"; }
      var t = svg("text", { x: 10, y: l2 ? 17 : 24 }); t.textContent = l1;
      if (l2) { var t2 = svg("tspan", { x: 10, dy: 14 }); t2.textContent = l2; t.appendChild(t2); }
      g.appendChild(t);
      g.addEventListener("click", function () { sel = id; drawAll(); jump(); });
      g.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); sel = id; drawAll(); jump(); } });
      gN.appendChild(g);
    });
    s.appendChild(gE); s.appendChild(gN);
    host.appendChild(s);
  }

  /* ---------- редактор сцены ---------- */
  function charsEditor(n, rerender) {
    var box = h("div", { class: "stack" });
    (n.characters = n.characters || []).forEach(function (ch, i) {
      var idIn = h("input", { type: "text", list: "dl-chars", value: ch.id || "", placeholder: "код персонажа", oninput: function () { ch.id = idIn.value.trim(); touch(); } });
      box.appendChild(h("div", { class: "row" }, idIn, select(MOODS, ch.mood || "neutral", function (v) { ch.mood = v; touch(); }, "inline"),
        btn("×", function () { n.characters.splice(i, 1); touch(); rerender(); }, "x")));
    });
    if (n.characters.length < 3) box.appendChild(btn("+ персонаж", function () { n.characters.push({ id: CHARS[0], mood: "neutral" }); touch(); rerender(); }));
    return box;
  }
  function sceneLook(n, rerender) {
    var bg = h("input", { type: "text", list: "dl-bgs", value: n.scene || "", oninput: function () { n.scene = bg.value.trim() || "default"; touch(); } });
    var sp = h("input", { type: "text", value: n.speaker || "", placeholder: "Ситуация", oninput: function () { n.speaker = sp.value; touch(); } });
    return h("div", { class: "grid g2" },
      field("Фон (код картинки)", bg, "Файл появится в разделе «Графика», пока там заглушка."),
      field("Кто говорит", sp), h("div", {}, h("div", { class: "bf-l" }, "Персонажи в кадре"), charsEditor(n, rerender)));
  }
  function textArea(obj, key, rows, ph) {
    var t = h("textarea", { rows: rows || 3, placeholder: ph || "", oninput: function () { obj[key] = t.value; touch(); } });
    t.value = obj[key] || "";
    return t;
  }
  function effectsEditor(obj) {
    if (!meters().length) return h("div", { class: "small muted" }, "Шкал пока нет. Добавьте их во вкладке «Шкалы и события», чтобы выборы меняли отношения героев.");
    var row = h("div", { class: "minis" });
    meters().forEach(function (m) {
      var inp = h("input", { type: "number", min: -3, max: 3, step: 1, class: "num", value: String((obj.effects || {})[m.code] || 0),
        oninput: function () {
          var v = clampInt(inp.value, -3, 3); obj.effects = obj.effects || {};
          if (v) obj.effects[m.code] = v; else delete obj.effects[m.code];
          if (!Object.keys(obj.effects).length) delete obj.effects;
          inp.className = "num " + (v > 0 ? "pos" : v < 0 ? "neg" : ""); touch();
        } });
      inp.className = "num " + (((obj.effects || {})[m.code] || 0) > 0 ? "pos" : ((obj.effects || {})[m.code] || 0) < 0 ? "neg" : "");
      row.appendChild(h("label", { class: "mini", title: m.title }, h("span", {}, m.title || m.code), inp));
    });
    return row;
  }
  function scoresEditor(ch) {
    var sum = h("b", {}), row = h("div", { class: "minis" });
    function upd() { var t = 0; for (var k in (ch.scores || {})) t += ch.scores[k]; sum.textContent = (t > 0 ? "+" : "") + t; sum.className = t > 0 ? "pos" : t < 0 ? "neg" : ""; }
    comps().forEach(function (code) {
      var cur = (ch.scores || {})[code] || 0;
      var inp = h("input", { type: "number", min: -5, max: 5, step: 1, class: "num", value: String(cur),
        oninput: function () {
          var v = clampInt(inp.value, -5, 5); ch.scores = ch.scores || {};
          if (v) ch.scores[code] = v; else delete ch.scores[code];
          inp.className = "num " + (v > 0 ? "pos" : v < 0 ? "neg" : ""); upd(); touch();
        } });
      inp.className = "num " + (cur > 0 ? "pos" : cur < 0 ? "neg" : "");
      row.appendChild(h("label", { class: "mini", title: COMPS[code] || code }, h("span", {}, COMPS[code] || code), inp));
    });
    upd();
    return h("div", {}, row, h("div", { class: "small muted" }, "Сумма баллов за выбор: ", sum, " (от −5 до 5 по каждой компетенции)"));
  }
  function choiceCard(n, ch, i, rerender) {
    var card = h("div", { class: "bcard" });
    var tx = h("textarea", { rows: 2, placeholder: "Что делает или говорит педагог", oninput: function () { ch.text = tx.value; touch(); } }); tx.value = ch.text || "";
    card.appendChild(h("div", { class: "row sp" }, h("b", {}, "Вариант " + (i + 1)), h("span", { class: "row" },
      btn("↑", function () { if (i > 0) { n.choices.splice(i - 1, 0, n.choices.splice(i, 1)[0]); touch(); rerender(); } }, "x"),
      btn("↓", function () { if (i < n.choices.length - 1) { n.choices.splice(i + 1, 0, n.choices.splice(i, 1)[0]); touch(); rerender(); } }, "x"),
      btn("Удалить", function () { n.choices.splice(i, 1); touch(); rerender(); }, "danger"))));
    card.appendChild(tx);
    card.appendChild(h("div", { class: "bf-l" }, "Куда ведёт этот выбор"));
    card.appendChild(targetPicker(ch, "to"));
    card.appendChild(h("div", { class: "bf-l" }, "Баллы по компетенциям"));
    card.appendChild(scoresEditor(ch));
    card.appendChild(h("div", { class: "bf-l" }, "Как изменятся отношения (шкалы)"));
    card.appendChild(effectsEditor(ch));
    card.appendChild(h("div", { class: "bf-l" }, "Что запомнится после этого выбора"));
    card.appendChild(flagsEditor(ch, "flags", "запомнить событие"));
    var det = h("details", { class: "adv" }, h("summary", {}, ch.requires ? "Доступен не всегда (условие задано)" : "Дополнительно: условие доступности и пояснение"));
    if (ch.requires) det.open = true;
    det.appendChild(h("div", { class: "bf-l" }, "Этот вариант доступен, только если…"));
    det.appendChild(condEditor(ch, "requires", rerender));
    if (ch.requires) {
      var hint = h("input", { type: "text", value: ch.hint || "", placeholder: "Подсказка, пока вариант закрыт: что нужно выяснить", oninput: function () { ch.hint = hint.value; touch(); } });
      det.appendChild(field("Подсказка студенту (вариант виден, но закрыт)", hint, "Не раскрывайте скрытое: подскажите, где искать."));
    }
    det.appendChild(field("Пояснение после выбора (показывается в разборе)", textArea(ch, "feedback", 2, "Почему это сработало или нет")));
    card.appendChild(det);
    return card;
  }
  function autoEditor(n, rerender) {
    var box = h("div", { class: "stack" });
    n.auto = n.auto && n.auto.length ? n.auto : [{ to: "" }];
    n.auto.forEach(function (e, i) {
      var last = i === n.auto.length - 1, card = h("div", { class: "bcard" });
      card.appendChild(h("div", { class: "row sp" }, h("b", {}, last ? "Иначе (во всех остальных случаях)" : "Правило " + (i + 1)),
        last ? null : btn("Удалить правило", function () { n.auto.splice(i, 1); touch(); rerender(); }, "danger")));
      if (!last) { card.appendChild(h("div", { class: "bf-l" }, "Если…")); card.appendChild(condEditor(e, "if", rerender)); }
      card.appendChild(h("div", { class: "bf-l" }, last ? "Перейти в сцену" : "…перейти в сцену"));
      card.appendChild(targetPicker(e, "to"));
      var det = h("details", { class: "adv" }, h("summary", {}, "Дополнительно: сдвиг шкал и события при этом переходе"));
      det.appendChild(effectsEditor(e)); det.appendChild(flagsEditor(e, "flags", "запомнить событие"));
      card.appendChild(det);
      if (last && n.auto.length === 1 && !meters().length && !allFlags().length) card.appendChild(h("div", { class: "small muted" }, "Чтобы переход зависел от условий, заведите шкалы или события."));
      box.appendChild(card);
    });
    box.appendChild(btn("+ правило «если…»", function () {
      if (!leafDefault()) { alert("Сначала заведите шкалу или событие (вкладка «Шкалы и события»)."); return; }
      n.auto.splice(n.auto.length - 1, 0, { "if": leafDefault(), to: "" }); touch(); rerender();
    }));
    return box;
  }
  function drawEditor(host) {
    host.textContent = "";
    var n = graph.nodes[sel];
    if (!n) { host.appendChild(h("p", { class: "muted" }, "Выберите сцену слева или на схеме.")); return; }
    var k = kindOf(n), rerender = function () { drawEditor(host); drawSide(); fitAll(); };
    host.appendChild(h("div", { class: "row sp" }, h("h2", { style: "margin:0" }, KIND_NAME[k]),
      h("span", { class: "row" },
        graph.start === sel ? h("span", { class: "badge ok" }, "Начало кейса") : btn("Сделать началом кейса", function () { graph.start = sel; touch(); drawAll(); }),
        btn("Удалить сцену", function () { deleteNode(sel); }, "danger"))));
    var nameIn = h("input", { type: "text", value: (k === "final" ? n.title : n.name) || "", placeholder: "Короткое название для себя",
      oninput: function () { if (k === "final") n.title = nameIn.value; else n.name = nameIn.value; touch(); } });
    host.appendChild(field(k === "final" ? "Название концовки (его увидит студент)" : "Название сцены (видно только вам)", nameIn));
    if (k !== "router") host.appendChild(sceneLook(n, rerender));
    if (k !== "router") host.appendChild(field(k === "final" ? "Что произошло в итоге" : "Текст сцены", textArea(n, "text", 5, "Опишите ситуацию так, как её увидит студент")));
    if (k === "scene") {
      host.appendChild(h("h3", {}, "Варианты ответа"));
      var list = h("div", { class: "stack" });
      n.choices.forEach(function (ch, i) { list.appendChild(choiceCard(n, ch, i, rerender)); });
      host.appendChild(list);
      host.appendChild(btn("+ добавить вариант", function () { n.choices.push(newChoice(n)); touch(); rerender(); }, "primary"));
      host.appendChild(field("Комментарий методиста для разбора", textArea({ get t() { return review.node_notes[sel]; }, set t(v) { review.node_notes[sel] = v; } }, "t", 2, "Что здесь важно понять студенту"), "Показывается после прохождения."));
    } else if (k === "cut") {
      var bt = h("input", { type: "text", value: n.button || "", placeholder: "Далее", oninput: function () { if (bt.value) n.button = bt.value; else delete n.button; touch(); } });
      host.appendChild(field("Надпись на кнопке", bt));
      host.appendChild(h("div", { class: "bf-l" }, "Что запоминается при входе в эту сцену"));
      host.appendChild(flagsEditor(n, "set_flags", "запомнить событие"));
      host.appendChild(h("h3", {}, "Куда дальше"));
      host.appendChild(autoEditor(n, rerender));
    } else if (k === "router") {
      host.appendChild(h("p", { class: "muted small" }, "Студент не видит эту сцену: программа сама выбирает, куда идти дальше, по шкалам и событиям. Правила проверяются сверху вниз."));
      host.appendChild(autoEditor(n, rerender));
    } else {
      var oc = select([["success", "Успех"], ["partial", "Частичный результат"], ["fail", "Неудача"]], n.outcome, function (v) { n.outcome = v; touch(); drawSide(); });
      var bn = h("input", { type: "number", min: 0, max: 30, class: "num", value: String(n.bonus || 0), oninput: function () { n.bonus = clampInt(bn.value, 0, 30); touch(); } });
      host.appendChild(h("div", { class: "grid g2" }, field("Исход", oc), field("Бонусные баллы за концовку (0–30)", bn, "Чем лучше концовка, тем больше бонус.")));
      host.appendChild(field("Комментарий методиста к концовке", textArea({ get t() { return review.final_notes[sel]; }, set t(v) { review.final_notes[sel] = v; } }, "t", 2, "Почему получился такой итог")));
    }
  }

  /* ---------- боковой список ---------- */
  function drawSide() {
    var host = document.getElementById("bld-list"); if (host) {
      host.textContent = "";
      ["scene", "cut", "router", "final"].forEach(function (kind) {
        var items = ids().filter(function (id) { return kindOf(graph.nodes[id]) === kind; });
        if (!items.length) return;
        host.appendChild(h("div", { class: "bl-h" }, KIND_NAME[kind] + " · " + items.length));
        items.forEach(function (id) {
          var n = graph.nodes[id];
          host.appendChild(h("button", { type: "button", class: "bl-i k-" + kind + (kind === "final" ? " o-" + n.outcome : "") + (id === sel ? " sel" : ""), onclick: function () { sel = id; drawAll(); jump(); } },
            (id === graph.start ? "▶ " : "") + label(id)));
        });
      });
    }
    var map = document.getElementById("bld-map"); if (map) drawMap(map);
  }
  function drawAll() { var ed = document.getElementById("bld-editor"); if (ed) drawEditor(ed); drawSide(); fitAll(); }

  /* ---------- вкладка «Шкалы и события» ---------- */
  function drawSettings(host) {
    host.textContent = "";
    host.appendChild(h("h2", {}, "Шкалы"));
    host.appendChild(h("p", { class: "muted small" }, "Шкала — скрытое число, которое меняется от решений: например, «Доверие Артёма». От неё зависят, что расскажут герои, какие варианты откроются и чем закончится кейс. В зачёте студент их не видит."));
    var mbox = h("div", { class: "stack" });
    meters().forEach(function (m, i) {
      var nm = h("input", { type: "text", value: m.title || "", placeholder: "Название шкалы", oninput: function () { m.title = nm.value; touch(); } });
      var mn = h("input", { type: "number", class: "num", value: String(m.min == null ? -3 : m.min), oninput: function () { m.min = clampInt(mn.value, -9, 0); touch(); } });
      var mx = h("input", { type: "number", class: "num", value: String(m.max == null ? 3 : m.max), oninput: function () { m.max = clampInt(mx.value, 0, 9); touch(); } });
      var st = h("input", { type: "number", class: "num", value: String(m.start || 0), oninput: function () { m.start = clampInt(st.value, -9, 9); touch(); } });
      mbox.appendChild(h("div", { class: "bcard" }, h("div", { class: "row" }, nm,
        btn("Удалить", function () {
          if (!window.confirm("Удалить шкалу «" + (m.title || m.code) + "»? Её сдвиги и условия будут убраны.")) return;
          removeMeter(m.code); drawSettings(host); touch();
        }, "danger")),
        h("div", { class: "minis" }, h("label", { class: "mini" }, h("span", {}, "Минимум"), mn), h("label", { class: "mini" }, h("span", {}, "Максимум"), mx), h("label", { class: "mini" }, h("span", {}, "Старт"), st))));
    });
    host.appendChild(mbox);
    host.appendChild(btn("+ шкала", function () {
      var i = 1; while (meters().some(function (m) { return m.code === "m" + i; })) i++;
      meters().push({ code: "m" + i, title: "Новая шкала", min: -3, max: 3, start: 0 }); touch(); drawSettings(host);
    }, "primary"));

    host.appendChild(h("h2", {}, "События (что запоминается)"));
    host.appendChild(h("p", { class: "muted small" }, "Событие — отметка «это произошло»: например, «Узнали про чат» или «Пообещали тайну». Ставится выбором или сценой, а проверяется в условиях. Название показывается студенту в разборе."));
    var fbox = h("div", { class: "stack" });
    var used = usedFlags();
    allFlags().forEach(function (f) {
      var t = h("input", { type: "text", value: flagTitles()[f] || "", placeholder: f, oninput: function () { flagTitles()[f] = t.value; touch(); } });
      fbox.appendChild(h("div", { class: "row" }, t, h("span", { class: "small muted" }, "где поставлено/проверяется: " + (used[f] || 0)),
        btn("Удалить", function () { if (!window.confirm("Удалить событие? Оно будет убрано из выборов и условий.")) return; removeFlag(f); drawSettings(host); touch(); }, "danger")));
    });
    if (!allFlags().length) fbox.appendChild(h("div", { class: "muted small" }, "Событий пока нет. Их можно создавать прямо в выборах: «+ запомнить событие → новое событие…»."));
    host.appendChild(fbox);
    host.appendChild(btn("+ событие", function () { if (newFlag()) { drawSettings(host); touch(); } }, "primary"));
    host.appendChild(h("h2", {}, "Начало кейса"));
    host.appendChild(field("Первая сцена", sceneSelect(graph.start, function (v) { graph.start = v; touch(); drawSide(); })));
  }
  function usedFlags() {
    var u = {};
    function bump(f) { u[f] = (u[f] || 0) + 1; }
    ids().forEach(function (id) {
      var n = graph.nodes[id], tmp;
      (n.set_flags || []).forEach(bump);
      (n.choices || []).forEach(function (c) { (c.flags || []).forEach(bump); tmp = {}; condFlags(c.requires, tmp); Object.keys(tmp).forEach(bump); });
      (n.auto || []).forEach(function (e) { (e.flags || []).forEach(bump); tmp = {}; condFlags(e["if"], tmp); Object.keys(tmp).forEach(bump); });
    });
    return u;
  }
  function stripFlagCond(c, f) { // возвращает условие без флага или null
    if (!c) return c;
    if (c.all || c.any) {
      var k = c.all ? "all" : "any";
      c[k] = c[k].map(function (x) { return stripFlagCond(x, f); }).filter(Boolean);
      return c[k].length ? c : null;
    }
    if (c.not) return stripFlagCond(c.not, f) ? c : null;
    return c.flag === f ? null : c;
  }
  function stripMeterCond(c, code) {
    if (!c) return c;
    if (c.all || c.any) {
      var k = c.all ? "all" : "any";
      c[k] = c[k].map(function (x) { return stripMeterCond(x, code); }).filter(Boolean);
      return c[k].length ? c : null;
    }
    if (c.not) return stripMeterCond(c.not, code) ? c : null;
    return c.meter === code ? null : c;
  }
  function removeFlag(f) {
    delete flagTitles()[f];
    ids().forEach(function (id) {
      var n = graph.nodes[id];
      if (n.set_flags) { n.set_flags = n.set_flags.filter(function (x) { return x !== f; }); if (!n.set_flags.length) delete n.set_flags; }
      (n.choices || []).forEach(function (c) {
        if (c.flags) { c.flags = c.flags.filter(function (x) { return x !== f; }); if (!c.flags.length) delete c.flags; }
        if (c.requires && !(c.requires = stripFlagCond(c.requires, f))) { delete c.requires; delete c.hint; }
      });
      (n.auto || []).forEach(function (e) {
        if (e.flags) { e.flags = e.flags.filter(function (x) { return x !== f; }); if (!e.flags.length) delete e.flags; }
        if (e["if"] && !(e["if"] = stripFlagCond(e["if"], f))) delete e["if"];
      });
    });
  }
  function removeMeter(code) {
    graph.meters = meters().filter(function (m) { return m.code !== code; });
    ids().forEach(function (id) {
      var n = graph.nodes[id];
      (n.choices || []).forEach(function (c) {
        if (c.effects) { delete c.effects[code]; if (!Object.keys(c.effects).length) delete c.effects; }
        if (c.requires && !(c.requires = stripMeterCond(c.requires, code))) { delete c.requires; delete c.hint; }
      });
      (n.auto || []).forEach(function (e) {
        if (e.effects) { delete e.effects[code]; if (!Object.keys(e.effects).length) delete e.effects; }
        if (e["if"] && !(e["if"] = stripMeterCond(e["if"], code))) delete e["if"];
      });
    });
  }

  /* ---------- вкладка «Разбор» ---------- */
  function drawReview(host) {
    host.textContent = "";
    host.appendChild(h("h2", {}, "Теория к кейсу"));
    host.appendChild(h("p", { class: "muted small" }, "Карточки с принципами, которые студент увидит после прохождения. Комментарии к сценам и концовкам пишутся прямо в этих сценах."));
    var box = h("div", { class: "stack" });
    review.theory.forEach(function (t, i) {
      var ti = h("input", { type: "text", value: t.title || "", placeholder: "Заголовок", oninput: function () { t.title = ti.value; touch(); } });
      box.appendChild(h("div", { class: "bcard" }, h("div", { class: "row" }, ti, btn("Удалить", function () { review.theory.splice(i, 1); touch(); drawReview(host); }, "danger")), textArea(t, "text", 3, "Объяснение")));
    });
    host.appendChild(box);
    host.appendChild(btn("+ карточка теории", function () { review.theory.push({ title: "", text: "" }); touch(); drawReview(host); }, "primary"));
    host.appendChild(h("h2", {}, "Главное (выводы)"));
    var tk = h("div", { class: "stack" });
    review.takeaways.forEach(function (t, i) {
      var inp = h("input", { type: "text", value: t, oninput: function () { review.takeaways[i] = inp.value; touch(); } });
      tk.appendChild(h("div", { class: "row" }, inp, btn("×", function () { review.takeaways.splice(i, 1); touch(); drawReview(host); }, "x")));
    });
    host.appendChild(tk);
    host.appendChild(btn("+ вывод", function () { review.takeaways.push(""); touch(); drawReview(host); }, "primary"));
  }

  /* ---------- каркас страницы ---------- */
  var panes = {};
  function showTab(name) {
    tab = name;
    Object.keys(panes).forEach(function (k) { panes[k].hidden = k !== name; });
    jsonPane.hidden = name !== "json";
    Array.prototype.forEach.call(root.querySelectorAll(".bld-tab"), function (b) { b.classList.toggle("on", b.dataset.tab === name); b.setAttribute("aria-selected", b.dataset.tab === name ? "true" : "false"); });
    if (name === "settings") drawSettings(panes.settings);
    if (name === "review") drawReview(panes.review);
    if (name === "scenes") drawAll();
    fitAll();
    if (name === "json") { gTa.value = JSON.stringify(graph, null, 1); rTa.value = JSON.stringify(review, null, 1); }
  }
  function build() {
    root.textContent = "";
    var dl = function (id, arr) { return h("datalist", { id: id }, arr.map(function (x) { return h("option", { value: x }); })); };
    var bgs = {}, chs = {};
    BGS.forEach(function (x) { bgs[x] = 1; }); CHARS.forEach(function (x) { chs[x] = 1; });
    ids().forEach(function (id) { var n = graph.nodes[id]; if (n.scene) bgs[n.scene] = 1; (n.characters || []).forEach(function (c) { if (c.id) chs[c.id] = 1; }); });
    root.appendChild(dl("dl-bgs", Object.keys(bgs))); root.appendChild(dl("dl-chars", Object.keys(chs)));
    var tabs = h("div", { class: "bld-tabs", role: "tablist" });
    [["scenes", "Сцены и переходы"], ["settings", "Шкалы и события"], ["review", "Разбор после прохождения"], ["json", "Для опытных (JSON)"]].forEach(function (t) {
      tabs.appendChild(h("button", { type: "button", class: "bld-tab", role: "tab", "data-tab": t[0], onclick: function () { if (tab === "json" && jsonDirty) applyJson(true); showTab(t[0]); } }, t[1]));
    });
    root.appendChild(tabs);
    statusBox = h("div", { class: "bld-status", role: "status", "aria-live": "polite" });
    root.appendChild(statusBox);

    var scenes = h("div", { class: "bld-scenes" },
      h("details", { class: "bld-mapbox", open: true }, h("summary", {}, "Схема: как сцены связаны (нажмите на сцену, чтобы открыть)"),
        h("div", { class: "bld-map", id: "bld-map" }),
        h("div", { class: "bld-legend small muted" }, "▶ начало · ", h("span", { class: "lg k-scene" }, "сцена"), h("span", { class: "lg k-cut" }, "пауза"), h("span", { class: "lg k-router" }, "автопереход"),
          h("span", { class: "lg o-success" }, "успех"), h("span", { class: "lg o-partial" }, "частично"), h("span", { class: "lg o-fail" }, "неудача"), " · пунктир: закрытый выбор или переход по условию")),
      h("div", { class: "bld-cols" },
        h("aside", { class: "bld-side" },
          h("div", { class: "bld-add" },
            btn("+ Сцена с выбором", function () { addAndSelect("scene"); }, "primary"), btn("+ Пауза «Далее»", function () { addAndSelect("cut"); }),
            btn("+ Автопереход", function () { addAndSelect("router"); }), btn("+ Концовка", function () { addAndSelect("final"); })),
          h("div", { class: "bld-list", id: "bld-list" })),
        h("section", { class: "bld-editor card", id: "bld-editor" })));
    panes.scenes = scenes; panes.settings = h("div", { class: "card" }); panes.review = h("div", { class: "card" });
    root.appendChild(scenes); root.appendChild(panes.settings); root.appendChild(panes.review);
    var help = h("details", { class: "bld-help" }, h("summary", {}, "Как это работает"),
      h("ul", {},
        h("li", {}, "Кейс — это сцены. В «Сцене с выбором» студент выбирает вариант, и каждый вариант ведёт в другую сцену."),
        h("li", {}, "Каждый выбор даёт баллы по компетенциям: плюс за хорошее решение, минус за плохое."),
        h("li", {}, "«Пауза» — сцена без выбора, только кнопка «Далее». «Автопереход» — невидимый развилка: программа сама выбирает сцену по шкалам и событиям."),
        h("li", {}, "«Шкалы» и «События» создают память кейса: варианты могут быть закрыты, пока студент не выяснил нужное."),
        h("li", {}, "Строка проверки сверху сразу показывает, чего не хватает; опубликовать можно, когда она зелёная.")));
    root.appendChild(help);
  }
  function applyJson(silent) {
    if (!load(gTa.value, rTa.value)) { alert("В JSON ошибка: " + parseError); return false; }
    build(); showTab(tab === "json" ? "json" : tab); drawAll(); sync(); runCheck();
    if (!silent) alert("Применено.");
    return true;
  }

  /* ---------- запуск ---------- */
  if (!load(gTa.value, rTa.value)) {
    root.appendChild(h("div", { class: "flash error" }, "Не удалось прочитать кейс: " + parseError + ". Исправьте во вкладке «Для опытных»."));
    jsonPane.hidden = false;
    document.getElementById("json-apply").addEventListener("click", function () { if (load(gTa.value, rTa.value)) location.reload(); else alert("Ошибка: " + parseError); });
    return;
  }
  build(); showTab("scenes"); runCheck();
  root.addEventListener("toggle", fitAll, true);
  window.addEventListener("resize", fitAll);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitAll);
  gTa.addEventListener("input", function () { jsonDirty = true; }); rTa.addEventListener("input", function () { jsonDirty = true; });
  document.getElementById("json-apply").addEventListener("click", function () { applyJson(false); jsonDirty = false; });
  form.addEventListener("submit", function () { if (!jsonDirty || tab !== "json") sync(); });
  window.addEventListener("beforeunload", function () { /* данные сохраняются кнопкой «Сохранить черновик» */ });
})();
