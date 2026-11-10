/* Генератор QR-кода: байтовый режим, уровни коррекции L и M, версии 1–6. Без зависимостей. */
const QR = (function () {
  // [всего кодовых слов данных, EC на блок, [размеры блоков данных]]
  const SPEC_L = {
    1: [19, 7, [19]],
    2: [34, 10, [34]],
    3: [55, 15, [55]],
    4: [80, 20, [80]],
    5: [108, 26, [108]],
    6: [136, 18, [68, 68]],
  };
  const SPEC_M = {
    1: [16, 10, [16]],
    2: [28, 16, [28]],
    3: [44, 26, [44]],
    4: [64, 18, [32, 32]],
    5: [86, 24, [43, 43]],
    6: [108, 16, [27, 27, 27, 27]],
  };
  const SPEC = { L: SPEC_L, M: SPEC_M };
  const ECI = { L: 1, M: 0 };
  const ALIGN = { 1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
 };
  const REMAINDER = { 1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7 };

  // ---- GF(256)
  const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function () {
    let x = 1;
    for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; }
    for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255];
  })();
  const mul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];

  function genPoly(n) {
    let p = [1];
    for (let i = 0; i < n; i++) {
      const q = [1, EXP[i]], r = new Array(p.length + 1).fill(0);
      for (let j = 0; j < p.length; j++) for (let k = 0; k < 2; k++) r[j + k] ^= mul(p[j], q[k]);
      p = r;
    }
    return p;
  }
  function ecBytes(data, n) {
    const g = genPoly(n), res = new Array(data.length + n).fill(0);
    data.forEach((b, i) => { res[i] = b; });
    for (let i = 0; i < data.length; i++) {
      const f = res[i];
      if (f === 0) continue;
      for (let j = 0; j < g.length; j++) res[i + j] ^= mul(g[j], f);
    }
    return res.slice(data.length);
  }

  function utf8(str) {
    const out = [], s = unescape(encodeURIComponent(str));
    for (let i = 0; i < s.length; i++) out.push(s.charCodeAt(i));
    return out;
  }

  function bitStream(bytes, ver, lvl) {
    const [total] = SPEC[lvl][ver], bits = [];
    const push = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >> i) & 1); };
    push(4, 4);               // байтовый режим
    push(bytes.length, 8);    // счётчик символов (версии 1–9 и 10 при байтовом: 8/16)
    bytes.forEach(b => push(b, 8));
    const cap = total * 8;
    for (let i = 0; i < 4 && bits.length < cap; i++) bits.push(0);
    while (bits.length % 8) bits.push(0);
    const pads = [0xec, 0x11];
    let k = 0;
    while (bits.length < cap) { push(pads[k++ % 2], 8); }
    const words = [];
    for (let i = 0; i < bits.length; i += 8) {
      let v = 0;
      for (let j = 0; j < 8; j++) v = (v << 1) | bits[i + j];
      words.push(v);
    }
    return words;
  }

  function codewords(str, ver, lvl) {
    const [, ecLen, sizes] = SPEC[lvl][ver];
    const words = bitStream(utf8(str), ver, lvl);
    const dataBlocks = [], ecBlocks = [];
    let p = 0;
    sizes.forEach(sz => {
      const d = words.slice(p, p + sz); p += sz;
      dataBlocks.push(d);
      ecBlocks.push(ecBytes(d, ecLen));
    });
    const out = [];
    const maxD = Math.max.apply(null, sizes);
    for (let i = 0; i < maxD; i++) dataBlocks.forEach(b => { if (i < b.length) out.push(b[i]); });
    for (let i = 0; i < ecLen; i++) ecBlocks.forEach(b => out.push(b[i]));
    return out;
  }

  function capacityBytes(ver, lvl) {
    const [total] = SPEC[lvl][ver];
    return total - 2;
  }
  function pickVersion(str, lvl) {
    const n = utf8(str).length;
    for (let v = 1; v <= 6; v++) if (capacityBytes(v, lvl) >= n) return v;
    throw new Error("Строка слишком длинная для QR-кода версии 6.");
  }

  // ---- матрица
  function build(str, lvl) {
    lvl = lvl || "M";
    const ver = pickVersion(str, lvl), n = ver * 4 + 17;
    const mat = [], fn = [];           // fn = служебный модуль (маска не применяется)
    for (let r = 0; r < n; r++) { mat.push(new Array(n).fill(0)); fn.push(new Array(n).fill(false)); }
    const set = (r, c, v) => { mat[r][c] = v ? 1 : 0; fn[r][c] = true; };

    const finder = (r0, c0) => {
      for (let r = -1; r <= 7; r++) for (let c = -1; c <= 7; c++) {
        const r1 = r0 + r, c1 = c0 + c;
        if (r1 < 0 || c1 < 0 || r1 >= n || c1 >= n) continue;
        const d = Math.max(Math.abs(r - 3), Math.abs(c - 3));
        set(r1, c1, r >= 0 && r <= 6 && c >= 0 && c <= 6 ? (d !== 2) : 0);
      }
    };
    finder(0, 0); finder(0, n - 7); finder(n - 7, 0);

    for (let i = 8; i < n - 8; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }

    const al = ALIGN[ver];
    al.forEach(r0 => al.forEach(c0 => {
      if ((r0 === 6 && c0 === 6) || (r0 === 6 && c0 === n - 7) || (r0 === n - 7 && c0 === 6)) return;
      for (let r = -2; r <= 2; r++) for (let c = -2; c <= 2; c++)
        set(r0 + r, c0 + c, Math.max(Math.abs(r), Math.abs(c)) !== 1);
    }));

    set(n - 8, 8, 1);                                       // тёмный модуль
    for (let i = 0; i < 9; i++) {                           // зоны формата
      if (!fn[8][i]) set(8, i, 0);
      if (!fn[i][8]) set(i, 8, 0);
    }
    for (let i = 0; i < 8; i++) { if (!fn[8][n - 1 - i]) set(8, n - 1 - i, 0); if (!fn[n - 1 - i][8]) set(n - 1 - i, 8, 0); }

    // данные зигзагом
    const words = codewords(str, ver, lvl);
    const bits = [];
    words.forEach(w => { for (let i = 7; i >= 0; i--) bits.push((w >> i) & 1); });
    for (let i = 0; i < REMAINDER[ver]; i++) bits.push(0);
    let bi = 0, up = true;
    for (let c = n - 1; c > 0; c -= 2) {
      if (c === 6) c--;                                     // пропуск столбца синхронизации
      for (let k = 0; k < n; k++) {
        const r = up ? n - 1 - k : k;
        for (const cc of [c, c - 1]) {
          if (fn[r][cc]) continue;
          mat[r][cc] = bi < bits.length ? bits[bi++] : 0;
        }
      }
      up = !up;
    }

    // маски
    const MASKS = [
      (r, c) => (r + c) % 2 === 0,
      (r, c) => r % 2 === 0,
      (r, c) => c % 3 === 0,
      (r, c) => (r + c) % 3 === 0,
      (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
      (r, c) => ((r * c) % 2 + (r * c) % 3) === 0,
      (r, c) => (((r * c) % 2 + (r * c) % 3) % 2) === 0,
      (r, c) => (((r + c) % 2 + (r * c) % 3) % 2) === 0,
    ];
    let bestM = 0, bestP = Infinity, bestG = null;
    for (let m = 0; m < 8; m++) {
      const g = mat.map((row, r) => row.map((v, c) => fn[r][c] ? v : (MASKS[m](r, c) ? v ^ 1 : v)));
      fmtInto(g, n, m, lvl);
      const p = penalty(g, n);
      if (p < bestP) { bestP = p; bestM = m; bestG = g; }
    }
    return { size: n, version: ver, level: lvl, mask: bestM, modules: bestG };
  }

  /* Остаток от деления на порождающий полином: ecBits — степень полинома. */
  function bch(data, poly, ecBits) {
    let rem = data;
    for (let i = 0; i < ecBits; i++) rem = (rem << 1) ^ (((rem >>> (ecBits - 1)) & 1) * poly);
    return (data << ecBits) | rem;
  }
  function fmtInto(g, n, mask, lvl) {
    const bits = bch((ECI[lvl] << 3) | mask, 0x537, 10) ^ 0x5412;
    const get = i => (bits >> (14 - i)) & 1;   // старший бит — в (8,0), как в стандарте
    for (let i = 0; i <= 5; i++) g[8][i] = get(i);
    g[8][7] = get(6); g[8][8] = get(7); g[7][8] = get(8);
    for (let i = 9; i <= 14; i++) g[14 - i][8] = get(i);
    for (let i = 0; i <= 6; i++) g[n - 1 - i][8] = get(i);
    for (let i = 7; i <= 14; i++) g[8][n - 15 + i] = get(i);
    g[n - 8][8] = 1;                           // всегда тёмный модуль
  }

  function penalty(g, n) {
    let p = 0;
    const runs = line => {
      let s = 0, prev = -1, run = 0;
      for (const v of line) {
        if (v === prev) run++;
        else { if (run >= 5) s += run - 2; prev = v; run = 1; }
      }
      if (run >= 5) s += run - 2;
      return s;
    };
    for (let r = 0; r < n; r++) p += runs(g[r]);
    for (let c = 0; c < n; c++) p += runs(g.map(row => row[c]));
    for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) {
      const v = g[r][c];
      if (v === g[r][c + 1] && v === g[r + 1][c] && v === g[r + 1][c + 1]) p += 3;
    }
    const pat = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0], rev = pat.slice().reverse();
    const hit = (line, i, q) => q.every((v, j) => line[i + j] === v);
    for (let r = 0; r < n; r++) for (let c = 0; c + 11 <= n; c++) {
      if (hit(g[r], c, pat) || hit(g[r], c, rev)) p += 40;
    }
    for (let c = 0; c < n; c++) {
      const col = g.map(row => row[c]);
      for (let r = 0; r + 11 <= n; r++) if (hit(col, r, pat) || hit(col, r, rev)) p += 40;
    }
    let dark = 0;
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) dark += g[r][c];
    p += Math.floor(Math.abs(dark * 100 / (n * n) - 50) / 5) * 10;
    return p;
  }

  function svg(str, opts) {
    const o = opts || {}, q = o.border === undefined ? 4 : o.border;
    const { size, modules } = build(str, o.level);
    const dim = size + q * 2;
    let d = "";
    for (let r = 0; r < size; r++) for (let c = 0; c < size; c++)
      if (modules[r][c]) d += "M" + (c + q) + " " + (r + q) + "h1v1h-1z";
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + dim + ' ' + dim +
      '" shape-rendering="crispEdges" role="img" aria-label="QR-код со ссылкой на сайт">' +
      '<rect width="' + dim + '" height="' + dim + '" fill="' + (o.light || "#fff") + '"/>' +
      '<path fill="' + (o.dark || "#000") + '" d="' + d + '"/></svg>';
  }

  return { build, svg, SPEC };
})();
if (typeof module !== "undefined") module.exports = QR;
