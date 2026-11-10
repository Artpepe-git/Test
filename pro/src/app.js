/* УчительPRO — браузерная версия. Все результаты хранятся локально, на устройстве. */
const SKEY = "upro:v1";
const $ = id => document.getElementById(id);
const esc = s => String(s === undefined || s === null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

let st = { name: "", group: "", theme: "", view: "cases", slug: null, mk: null,
           steps: [], done: {}, log: [], mkcode: false };
try {
  const raw = localStorage.getItem(SKEY);
  if (raw) {
    const d = JSON.parse(raw);
    if (d && typeof d === "object") st = Object.assign(st, d, { view: "cases", slug: null, mk: null });
  }
} catch (e) {}
function keep() { try { localStorage.setItem(SKEY, JSON.stringify(st)); } catch (e) {} }
function theme() {
  if (st.theme === "green") document.documentElement.setAttribute("data-theme", "green");
  else document.documentElement.removeAttribute("data-theme");
}

// ---------- данные кейса
const BY_SLUG = {};
CASES.forEach(c => { BY_SLUG[c.slug] = c; });
const CACHE = {};
function engine(slug) {
  if (CACHE[slug]) return CACHE[slug];
  const c = BY_SLUG[slug];
  const g = { start: c.start, competencies: c.competencies, nodes: c.nodes,
              meters: c.meters || [], flag_titles: c.flag_titles || {} };
  const eng = new Engine(g);
  CACHE[slug] = { g, eng, ana: analyze(g, eng) };
  return CACHE[slug];
}
function position(slug, steps) {              // текущий узел и состояние по списку шагов
  const { g, eng } = engine(slug);
  let [nid, s] = eng.start();
  for (const x of steps) {
    if (x.node_id !== nid) throw new Error("Шаг не совпадает с кейсом.");
    [nid, s] = eng.take(nid, s, x.choice_id);
  }
  return { nid, s, node: g.nodes[nid], g, eng };
}
const stars = n => '<span class="stars">' + [1, 2, 3].map(i =>
  i <= n ? "★" : '<i>★</i>').join("") + "</span>";
const charTitle = id => CHARS[id] || id;
const sceneTitle = s => SCENES[s] || "";
const MOODS = { angry: "злится", sad: "грустит", happy: "радуется", neutral: "" };
const OUTCOMES = { success: "Успех", partial: "Частичный результат", fail: "Неудача" };
const RATINGS = { best: "Оптимальный выбор", good: "Приемлемо", weak: "Слабый выбор" };
function plural(n, a, b, c) {
  const m10 = n % 10, m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return a;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return b;
  return c;
}

// ---------- общие куски
function topLine() {
  const who = st.name ? " · " + esc(st.name) + (st.group ? ", " + esc(st.group) : "") : "";
  return '<div class="top"><span><b>УчительPRO</b>' + who + '</span>' +
    '<span class="t"><button class="lnk" id="thm">' + (st.theme === "green" ? "синяя тема" : "зелёная тема") + "</button></span></div>";
}
function nav() {
  const items = [["cases", "Кейсы"], ["mk", "МК"], ["me", "Результаты"], ["qr", "QR"]];
  return '<div class="nav">' + items.map(([k, t]) =>
    '<button data-go="' + k + '" class="' + (st.view === k || (k === "cases" && st.view === "case") ||
      (k === "mk" && st.view === "mkshow") ? "on" : "") + '">' + t + "</button>").join("") + "</div>";
}

// ---------- список кейсов
function vCases() {
  let out = topLine() + nav() +
    '<div class="col"><h1>Кейсы</h1><p class="muted">Ситуации с ветвлением: выбор меняет развитие событий. ' +
    "После прохождения — разбор каждого шага. Результаты сохраняются только в этом браузере.</p></div>";
  const list = CASES.slice().sort((a, b) => a.difficulty - b.difficulty || a.duration_min - b.duration_min);
  out += '<div class="cards">' + list.map(c => {
    const d = st.done[c.slug];
    const badge = d ? '<span class="badge ' + (d.outcome === "success" ? "done" : d.outcome === "fail" ? "fail" : "part") +
      '">' + stars(d.stars) + "</span>" : "";
    return '<button class="card" data-case="' + c.slug + '"><div class="hd"><h3>' + esc(c.title) + "</h3>" + badge + "</div>" +
      '<p class="small muted">' + esc(c.description) + "</p>" +
      '<div class="tags"><span class="tag">' + stars(Math.min(c.difficulty, 3)) +
      (c.difficulty > 3 ? " сложный" : "") + '</span><span class="tag">' + c.duration_min + " мин</span>" +
      '<span class="tag">' + esc(c.category) + "</span>" +
      (d ? '<span class="tag">попыток: ' + d.attempts + "</span>" : "") + "</button>";
  }).join("") + "</div>";
  if (!st.name) {
    out += '<div class="panel col"><h3>Подписать результаты</h3>' +
      '<p class="small muted">Необязательно: имя нужно только чтобы показать результат преподавателю.</p>' +
      '<label class="f" for="nm">Фамилия и имя<input type="text" id="nm" autocomplete="name" placeholder="Иванов Иван"></label>' +
      '<label class="f" for="gr">Группа<input type="text" id="gr" placeholder="К2083-26"></label>' +
      '<button class="btn sm ghost" id="saveme" style="align-self:flex-start">Сохранить</button></div>';
  }
  return out;
}

// ---------- карточка кейса
function vCase() {
  const c = BY_SLUG[st.slug], d = st.done[c.slug];
  const { ana } = engine(c.slug);
  const comps = c.competencies.map(k => esc(COMP[k] || k)).join(", ");
  const unfinished = st.steps.length > 0;
  return topLine() + nav() + '<div class="col"><h1>' + esc(c.title) + "</h1>" +
    '<div class="tags"><span class="tag">' + esc(c.category) + '</span><span class="tag">' +
    stars(Math.min(c.difficulty, 3)) + (c.difficulty > 3 ? " сложный" : "") + '</span><span class="tag">' +
    c.duration_min + " мин</span></div></div>" +
    '<div class="panel col"><p>' + esc(c.description) + "</p>" +
    '<p class="small muted">Компетенции: ' + comps + "</p>" +
    '<p class="small muted">Развилок в кейсе: ' + ana.golden_path.length + ", путей: " + ana.path_count + ".</p>" +
    (d ? '<p class="small">Лучший результат: ' + stars(d.stars) + " " + Math.round(d.pct * 100) + "% · " +
      esc(OUTCOMES[d.outcome]) + "</p>" : "") + "</div>" +
    '<div class="row">' + (unfinished ? '<button class="btn" id="resume">Продолжить</button>' : "") +
    '<button class="btn' + (unfinished ? " ghost" : "") + '" id="play">' +
    (unfinished ? "Начать заново" : d ? "Пройти ещё раз" : "Начать кейс") + "</button>" +
    '<button class="btn ghost" data-go="cases">К списку</button></div>';
}

// ---------- прохождение
function vPlay() {
  const c = BY_SLUG[st.slug];
  let pos;
  try { pos = position(st.slug, st.steps); }
  catch (e) { st.steps = []; pos = position(st.slug, st.steps); }
  const { nid, s, node, g, eng } = pos;
  if (node.final) return vFinal(nid);          // на случай возврата к завершённой попытке
  const { ana } = engine(st.slug);
  const total = Math.max(ana.golden_path.length, st.steps.filter(x => x.choice_id !== "next").length + 1);
  const made = st.steps.filter(x => x.choice_id !== "next").length;

  let out = topLine() +
    '<div class="col"><div class="steps">' + Array.from({ length: total }, (_, i) =>
      '<i class="' + (i < made ? "done" : i === made ? "cur" : "") + '"></i>').join("") + "</div>" +
    '<span class="small muted">' + esc(c.title) + (sceneTitle(node.scene) ? " · " + esc(sceneTitle(node.scene)) : "") + "</span></div>";

  const prev = st.steps.length ? lastChoiceText() : "";
  out += '<div class="panel scene">';
  if ((node.characters || []).length) {
    out += '<div class="chars">' + node.characters.map(ch => {
      const t = charTitle(ch.id), mood = MOODS[ch.mood || "neutral"];
      return '<span class="ch"><em>' + esc(t.slice(0, 1)) + "</em><b>" + esc(t) + "</b>" +
        (mood ? "<span>" + esc(mood) + "</span>" : "") + "</span>";
    }).join("") + "</div>";
  }
  if (prev) out += '<p class="prev">Ваш выбор: ' + esc(prev) + "</p>";
  if (node.speaker) out += '<p class="speaker">' + esc(node.speaker) + "</p>";
  out += '<p class="text">' + esc(node.text) + "</p>";

  if (eng.meters.length) {
    out += '<div class="meters">' + eng.meters.map((m, i) => {
      const lo = eng.lo[i], hi = eng.hi[i], v = s.m[i];
      const w = hi > lo ? (v - lo) / (hi - lo) * 100 : 0;
      return '<span class="meter"><span>' + esc(m.title || m.code) + "</span><span>" + (v > 0 ? "+" : "") + v +
        '</span><span class="tr"><i style="left:0;width:' + w.toFixed(1) + '%"></i></span></span>';
    }).join("") + "</div>";
  }
  const choices = node.kind === "cut"
    ? [{ id: "next", text: node.button || "Далее", locked: false, hint: "" }]
    : node.choices.map(ch => ({ id: ch.id, text: ch.text, locked: !eng.available(ch, s), hint: ch.hint || "" }));
  out += '<div class="choices">' + choices.map(ch =>
    '<button class="choice' + (ch.locked ? " locked" : "") + '" data-ch="' + esc(ch.id) + '"' +
    (ch.locked ? " disabled" : "") + ">" + esc(ch.text) +
    (ch.locked && ch.hint ? '<span class="hint">Закрыто: ' + esc(ch.hint) + "</span>" : "") + "</button>").join("") + "</div>";
  out += "</div>";
  out += '<div class="row"><button class="btn ghost sm" id="quit">Выйти в список</button>' +
    (st.steps.length ? '<button class="btn ghost sm" id="undo">Шаг назад</button>' : "") + "</div>";
  return out;
}
function lastChoiceText() {
  const steps = st.steps.slice(0, -1), last = st.steps[st.steps.length - 1];
  const { node } = position(st.slug, steps);
  if (!node.choices || last.choice_id === "next") return "";
  const ch = node.choices.find(x => x.id === last.choice_id);
  return ch ? ch.text : "";
}

// ---------- итоги
function vFinal(finalId) {
  const c = BY_SLUG[st.slug], { g, ana, eng } = engine(st.slug);
  const sum = summarize(g, ana, st.steps, finalId, eng);
  const node = g.nodes[finalId];
  const pct = Math.round(sum.pct * 100);
  let out = topLine() + nav() + '<div class="col"><span class="small muted">' + esc(c.title) + "</span>" +
    '<div class="hero"><span class="big stars">' + [1, 2, 3].map(i => i <= sum.stars ? "★" : '<i>★</i>').join("") + "</span>" +
    "<h1>" + esc(node.title || OUTCOMES[sum.outcome]) + "</h1>" +
    '<span class="muted">' + esc(OUTCOMES[sum.outcome]) + " · " + pct + "% от оптимума</span></div></div>";
  if (node.text) out += '<div class="panel"><p class="text">' + esc(node.text) + "</p></div>";
  out += '<div class="panel col"><div class="kv"><span>Набрано баллов</span><b>' + sum.earned +
    " из " + sum.best_total + "</b>" +
    "<span>Оптимальных выборов</span><b>" + sum.counts.best + "</b>" +
    "<span>Приемлемых</span><b>" + sum.counts.good + "</b>" +
    "<span>Слабых</span><b>" + sum.counts.weak + "</b></div>";
  if (sum.competencies.length) {
    out += '<div class="bars">' + sum.competencies.map(r =>
      '<span class="bar"><span>' + esc(COMP[r.code] || r.code) + "</span><span>" +
      (r.pct === null ? "—" : r.pct + "%") + '</span><span class="tr"><i style="width:' +
      (r.pct === null ? 0 : r.pct) + '%"></i></span></span>').join("") + "</div>";
  }
  if (sum.flags.length) out += '<p class="small muted">По ходу кейса: ' + sum.flags.map(esc).join("; ") + ".</p>";
  out += "</div>";
  out += '<div class="row"><button class="btn" id="debrief">Разбор по шагам</button>' +
    '<button class="btn ghost" id="again">Пройти заново</button>' +
    '<button class="btn ghost" data-go="cases">К списку кейсов</button></div>';
  return out;
}

// ---------- разбор
function vDebrief() {
  const c = BY_SLUG[st.slug], { g, ana, eng } = engine(st.slug);
  const finalId = position(st.slug, st.steps).nid;
  const sum = summarize(g, ana, st.steps, finalId, eng);
  const rev = c.review || {};
  let out = topLine() + nav() + '<div class="col"><h1>Разбор</h1><span class="muted">' + esc(c.title) + "</span></div>";
  out += '<div class="col">' + sum.path.map((p, i) => {
    const note = (rev.node_notes || {})[p.node_id];
    return '<div class="step"><span class="r ' + p.rating + '">' + esc(RATINGS[p.rating]) + " · " +
      (p.points > 0 ? "+" : "") + p.points + " " + plural(Math.abs(p.points), "балл", "балла", "баллов") + "</span>" +
      '<span class="q">Шаг ' + (i + 1) + (note ? ". " + esc(note) : "") + "</span>" +
      "<b>" + esc(p.choice_text) + "</b>" +
      (p.feedback ? '<span class="fb">' + esc(p.feedback) + "</span>" : "") +
      (p.rating !== "best" ? '<span class="alt">Сильнее было бы: ' + esc(p.best_text) + "</span>" : "") + "</div>";
  }).join("") + "</div>";
  const fn = (rev.final_notes || {})[finalId];
  if (fn) out += '<div class="panel"><h3>Про этот финал</h3><p class="small" style="margin-top:6px">' + esc(fn) + "</p></div>";
  if ((rev.theory || []).length) {
    out += '<div class="panel col"><h2>Теория</h2>' + rev.theory.map(t =>
      "<div><h3>" + esc(t.title) + '</h3><p class="small muted" style="margin-top:4px">' + esc(t.text) + "</p></div>").join("") + "</div>";
  }
  if ((rev.takeaways || []).length) {
    out += '<div class="panel col"><h2>Главное</h2><ul class="ls small">' +
      rev.takeaways.map(t => "<li>" + esc(t) + "</li>").join("") + "</ul></div>";
  }
  out += '<div class="row"><button class="btn" id="again">Пройти заново</button>' +
    '<button class="btn ghost" data-go="cases">К списку кейсов</button>' +
    '<button class="btn ghost" id="print">Распечатать разбор</button></div>';
  return out;
}

// ---------- мои результаты
function vMe() {
  const slugs = Object.keys(st.done);
  let out = topLine() + nav() + '<div class="col"><h1>Мои результаты</h1>' +
    '<p class="muted small">Сохраняются только в этом браузере: другой телефон или режим инкогнито их не увидят. ' +
    "Преподавателю результат показывают с экрана или выгружают файлом.</p></div>";
  if (!slugs.length) return out + '<div class="panel"><p class="muted">Пока ничего не пройдено.</p></div>';
  const agg = {};
  slugs.forEach(s => (st.done[s].comp || []).forEach(r => {
    if (r.max > 0) { agg[r.code] = agg[r.code] || [0, 0]; agg[r.code][0] += r.earned; agg[r.code][1] += r.max; }
  }));
  const codes = Object.keys(agg);
  if (codes.length) {
    out += '<div class="panel col"><h2>Профиль компетенций</h2><p class="small muted">По лучшей попытке каждого кейса.</p>' +
      '<div class="bars">' + codes.map(k => {
        const p = Math.min(100, Math.round(agg[k][0] / agg[k][1] * 100));
        return '<span class="bar"><span>' + esc(COMP[k] || k) + "</span><span>" + p +
          '%</span><span class="tr"><i style="width:' + p + '%"></i></span></span>';
      }).join("") + "</div></div>";
  }
  out += '<div class="cards">' + slugs.map(s => {
    const d = st.done[s], c = BY_SLUG[s];
    if (!c) return "";
    return '<button class="card" data-case="' + s + '"><div class="hd"><h3>' + esc(c.title) + "</h3>" +
      '<span class="badge ' + (d.outcome === "success" ? "done" : d.outcome === "fail" ? "fail" : "part") + '">' +
      stars(d.stars) + "</span></div><div class=\"tags\"><span class=\"tag\">" + Math.round(d.pct * 100) +
      "%</span><span class=\"tag\">" + esc(OUTCOMES[d.outcome]) + '</span><span class="tag">попыток: ' +
      d.attempts + "</span></div></button>";
  }).join("") + "</div>";
  out += '<div class="row"><button class="btn ghost" id="export">Скачать результаты файлом</button>' +
    '<button class="btn ghost" id="copy">Скопировать для преподавателя</button>' +
    '<button class="btn ghost" id="wipe">Удалить всё</button></div>';
  return out;
}
function record(slug, sum) {
  const prev = st.done[slug];
  const row = { stars: sum.stars, pct: sum.pct, outcome: sum.outcome,
                attempts: (prev ? prev.attempts : 0) + 1, ts: Date.now(),
                comp: sum.competencies.map(r => ({ code: r.code, earned: r.earned, max: r.max })) };
  if (!prev || sum.pct > prev.pct) st.done[slug] = row;
  else { prev.attempts = row.attempts; prev.ts = row.ts; }
  st.log.push({ slug, ts: row.ts, stars: sum.stars, pct: +sum.pct.toFixed(4), outcome: sum.outcome });
  if (st.log.length > 200) st.log = st.log.slice(-200);
  keep();
}
function plainReport() {
  const lines = ["УчительPRO — результаты", st.name ? st.name + (st.group ? ", " + st.group : "") : "без имени", ""];
  Object.keys(st.done).forEach(s => {
    const d = st.done[s], c = BY_SLUG[s];
    if (c) lines.push("• " + c.title + ": " + "★".repeat(d.stars) + "☆".repeat(3 - d.stars) + " " +
      Math.round(d.pct * 100) + "%, " + OUTCOMES[d.outcome] + ", попыток " + d.attempts);
  });
  return lines.join("\n");
}

// ---------- мастер-классы
function vMK() {
  let out = topLine() + nav() + '<div class="col"><h1>Мастер-классы</h1>' +
    '<p class="muted small">Готовые сценарии: тайминг, реплики ведущего и материалы.</p></div>';
  out += '<div class="cards">' + MK.map(m => {
    const open = m.roles.indexOf("student") >= 0;
    return '<button class="card" data-mk="' + esc(m.slug) + '"><div class="hd"><h3>' + esc(m.title) + "</h3>" +
      '<span class="tag">' + esc(m.tag) + "</span></div>" +
      '<p class="small muted">' + esc(m.subtitle) + "</p>" +
      '<div class="tags"><span class="tag">' + m.total_min + " мин</span><span class=\"tag\">" +
      (open ? "для всех" : "для преподавателей") + "</span></div></button>";
  }).join("") + "</div>";
  return out;
}
function vMKShow() {
  const m = MK.find(x => x.slug === st.mk);
  const open = m.roles.indexOf("student") >= 0;
  let out = topLine() + nav() + '<div class="col"><h1>' + esc(m.title) + "</h1>" +
    '<span class="muted">' + esc(m.subtitle) + "</span></div>";
  if (!open && !st.mkcode) {
    return out + '<div class="panel col"><h3>Материал для преподавателей</h3>' +
      '<p class="small muted">Введите код, который даёт преподаватель. Код лежит в коде страницы — это не защита, ' +
      "а напоминание, что материал не для студентов.</p>" +
      '<label class="f" for="code">Код<input type="text" id="code" placeholder="код"></label>' +
      '<button class="btn sm" id="codeok" style="align-self:flex-start">Открыть</button>' +
      '<p class="err" id="codeerr" hidden>Код не подошёл.</p></div>' +
      '<div class="row"><button class="btn ghost" data-go="mk">Назад</button></div>';
  }
  out += '<div class="panel"><div class="mkmeta">' + m.meta.map(([k, v]) =>
    "<b>" + esc(k) + "</b><span>" + esc(v) + "</span>").join("") + "</div></div>";
  out += '<div class="col">' + m.blocks.map(b =>
    '<div class="mkblock"><span class="n">Блок ' + b.n + " · " + b.minutes + ' мин</span><h3>' + esc(b.title) + "</h3>" +
    renderItems(b.items) + "</div>").join("") + "</div>";
  if ((m.closing || []).length) {
    out += '<div class="mkblock"><span class="n">' + esc(m.closing_title || "Итог") + "</span>" + renderItems(m.closing) + "</div>";
  }
  out += '<div class="row"><button class="btn ghost" data-go="mk">К мастер-классам</button>' +
    '<button class="btn ghost" id="print">Распечатать</button>' +
    '<a class="btn ghost" href="' + esc(DOCX_BASE + m.file) + '" download>Скачать .docx</a></div>';
  return out;
}
function renderItems(items) {
  let out = "", open = "", n = 0;
  items.forEach(it => {
    const want = it.t === "num" ? "ol" : it.t === "bullet" ? "ul" : "";
    if (want !== open) { if (open) out += "</" + open + ">"; if (want) out += '<' + want + ' class="ls small">'; open = want; }
    if (it.t === "say") out += '<blockquote class="say">' + esc(it.v) + "</blockquote>";
    else if (it.t === "note") out += '<p class="mknote">' + esc(it.v) + "</p>";
    else if (want) out += "<li>" + esc(it.v) + "</li>";
    else out += '<p class="small">' + esc(it.v) + "</p>";
  });
  if (open) out += "</" + open + ">";
  return out;
}

// ---------- QR
function vQR() {
  const url = location.href.split("#")[0];
  let svg = "";
  try { svg = QR.svg(url, { level: "M", border: 2, dark: "#000", light: "#fff" }); }
  catch (e) { svg = ""; }
  return topLine() + nav() + '<div class="panel qrbox"><h2>Откройте на телефоне</h2>' +
    '<p class="small muted">Наведите камеру на код — сайт откроется на любом устройстве.</p>' +
    (svg ? '<div class="b">' + svg + "</div>" : '<p class="err">QR-код не удалось построить.</p>') +
    '<p class="link">' + esc(url) + "</p>" +
    '<button class="btn ghost sm" id="print">Распечатать код</button></div>';
}

// ---------- сборка
function render() {
  theme();
  const v = st.view;
  const html = v === "cases" ? vCases() : v === "case" ? vCase() : v === "play" ? vPlay() :
    v === "debrief" ? vDebrief() : v === "me" ? vMe() : v === "mk" ? vMK() :
    v === "mkshow" ? vMKShow() : v === "qr" ? vQR() : vCases();
  $("app").innerHTML = html;
  bind();
  window.scrollTo(0, 0);
}
function bind() {
  const app = $("app");
  app.querySelectorAll("[data-go]").forEach(b => b.onclick = () => { st.view = b.dataset.go; keep(); render(); });
  app.querySelectorAll("[data-case]").forEach(b => b.onclick = () => {
    const slug = b.dataset.case;
    if (st.pending !== slug) st.steps = [];        // незаконченная попытка живёт только для своего кейса
    st.slug = slug; st.view = "case"; keep(); render();
  });
  app.querySelectorAll("[data-mk]").forEach(b => b.onclick = () => { st.mk = b.dataset.mk; st.view = "mkshow"; keep(); render(); });
  app.querySelectorAll("[data-ch]").forEach(b => b.onclick = () => {
    const { nid } = position(st.slug, st.steps);
    st.steps.push({ node_id: nid, choice_id: b.dataset.ch });
    st.pending = st.slug;
    const now = position(st.slug, st.steps);
    if (now.node.final) finish(now.nid);           // засчитываем попытку один раз
    keep(); render();
  });
  const on = (id, fn) => { const el = $(id); if (el) el.onclick = fn; };
  on("thm", () => { st.theme = st.theme === "green" ? "" : "green"; keep(); render(); });
  on("saveme", () => {
    st.name = ($("nm").value || "").trim(); st.group = ($("gr").value || "").trim(); keep(); render();
  });
  on("play", () => { st.steps = []; st.pending = st.slug; st.view = "play"; keep(); render(); });
  on("resume", () => { st.view = "play"; keep(); render(); });
  on("again", () => { st.steps = []; st.pending = st.slug; st.view = "play"; keep(); render(); });
  on("quit", () => { st.view = "cases"; keep(); render(); });
  on("undo", () => { st.steps.pop(); keep(); render(); });
  on("debrief", () => { st.view = "debrief"; keep(); render(); });
  on("print", () => window.print());
  on("export", () => {
    const blob = new Blob([JSON.stringify({ name: st.name, group: st.group, done: st.done, log: st.log }, null, 1)],
      { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "uchitelpro-" + (st.name ? st.name.replace(/\s+/g, "-") : "результаты") + ".json";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });
  on("copy", () => {
    const t = plainReport();
    if (navigator.clipboard) navigator.clipboard.writeText(t).then(() => alertish("Скопировано"), () => show(t));
    else show(t);
  });
  on("wipe", () => {
    if (st.wipe) { st = { name: "", group: "", theme: st.theme, view: "me", slug: null, mk: null, steps: [], done: {}, log: [] }; keep(); render(); }
    else { st.wipe = true; alertish("Нажмите ещё раз, чтобы удалить все результаты"); }
  });
  on("codeok", () => {
    if (($("code").value || "").trim().toUpperCase() === MK_CODE) { st.mkcode = true; keep(); render(); }
    else $("codeerr").hidden = false;
  });
}
/* Попытка дошла до финала: записываем результат один раз. */
function finish(finalId) {
  const { g, ana, eng } = engine(st.slug);
  record(st.slug, summarize(g, ana, st.steps, finalId, eng));
}
function alertish(msg) {
  const d = document.createElement("div");
  d.textContent = msg;
  d.style.cssText = "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:9;background:var(--surface-raised);" +
    "border:1px solid var(--border-strong);border-radius:10px;padding:10px 16px;font-size:14px;box-shadow:var(--shadow)";
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 1800);
}
function show(t) {
  const d = document.createElement("textarea");
  d.value = t; d.style.cssText = "position:fixed;inset:10% 6%;z-index:9;padding:12px;border-radius:10px";
  document.body.appendChild(d); d.select();
  d.onblur = () => d.remove();
}

/* фон «волна» */
(function wall() {
  const cv = document.createElement("canvas");
  $("wall").appendChild(cv);
  const ctx = cv.getContext("2d");
  let w, h, t = 0;
  function size() {
    w = cv.width = innerWidth * devicePixelRatio; h = cv.height = innerHeight * devicePixelRatio;
  }
  size(); addEventListener("resize", size);
  function frame() {
    ctx.clearRect(0, 0, w, h);
    const col = getComputedStyle(document.documentElement).getPropertyValue("--wave").trim() || "#a9c8ff";
    ctx.strokeStyle = col; ctx.lineWidth = devicePixelRatio;
    for (let i = 0; i < 9; i++) {
      ctx.globalAlpha = 0.05 + i * 0.012;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 12 * devicePixelRatio) {
        const y = h * 0.62 + Math.sin(x / (170 * devicePixelRatio) + t + i * 0.42) * (16 + i * 7) * devicePixelRatio + i * 9 * devicePixelRatio;
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1; t += 0.006;
    requestAnimationFrame(frame);
  }
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) frame();
})();

render();
