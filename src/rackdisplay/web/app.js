"use strict";
/* The kiosk page. Every value from the server is put on the page with textContent: nothing is
   ever parsed as HTML, so a hostile host or container name cannot inject markup. */

const params = new URLSearchParams(location.search);
const token = params.get("token");
const SVG = "http://www.w3.org/2000/svg";
const LABEL = { ok: "OK", warn: "WARN", crit: "CRIT", unknown: "NO DATA" };

let cfg = { title: "Rack", rotate_seconds: 15, screens: ["overview"], interval: 5 };
let snap = null;
let failed = false;
let screenIndex = 0;
let shownAt = Date.now();
let pinned = params.get("screen");

const $ = (id) => document.getElementById(id);

function h(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined && text !== null) el.textContent = text;
  return el;
}

/* ---------- formatting ---------- */
const pct = (v) => (v === null || v === undefined ? "--" : Math.round(v * 100));
function bytes(v) {
  const units = [["T", 1024 ** 4], ["G", 1024 ** 3], ["M", 1024 ** 2]];
  for (const [u, s] of units) if (v >= s) return (v / s >= 10 ? Math.round(v / s) : (v / s).toFixed(1)) + u;
  return Math.round(v / 1024) + "K";
}
function rate(v) {
  if (v === null || v === undefined) return "--";
  const units = [["GB/s", 1e9], ["MB/s", 1e6], ["KB/s", 1e3]];
  for (const [u, s] of units) if (v >= s) return (v / s >= 10 ? Math.round(v / s) : (v / s).toFixed(1)) + " " + u;
  return Math.round(v) + " B/s";
}
function span(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  const d = Math.floor(seconds / 86400), hr = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${hr}h` : `${hr}h ${m}m`;
}

/* ---------- building blocks ---------- */
function ring(label, value, status) {
  const box = h("div", "ring");
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 36 36");
  for (const cls of ["track", "value " + status + "-s"]) {
    const c = document.createElementNS(SVG, "circle");
    c.setAttribute("cx", "18"); c.setAttribute("cy", "18"); c.setAttribute("r", "15.9155");
    c.setAttribute("pathLength", "100");
    c.setAttribute("class", cls);
    if (cls !== "track") c.setAttribute("stroke-dasharray", `${Math.max(0, Math.min(100, (value || 0) * 100))} 100`);
    svg.appendChild(c);
  }
  const num = h("div", "num", String(pct(value)));
  num.appendChild(h("small", "", label));
  box.append(svg, num);
  return box;
}
function levelOf(v, warn, crit) { return v === null || v === undefined ? "unknown" : v >= crit ? "crit" : v >= warn ? "warn" : "ok"; }
function bar(value) {
  const b = h("div", "bar"), s = document.createElement("span");
  s.style.width = Math.max(0, Math.min(100, value * 100)) + "%";
  b.appendChild(s);
  return b;
}
function row(status, label, sub, barValue, detail) {
  const r = h("div", "row " + status);
  const l = h("div", "label", label);
  if (sub) l.appendChild(h("small", "", sub));
  r.append(l, barValue === null ? h("div") : bar(barValue), detail);
  return r;
}
function fact(label, value) {
  const f = h("span");
  f.append(label + " ");
  f.appendChild(h("b", "", value));
  return f;
}
function tile(value, label, status) {
  const t = h("div", "tile " + status);
  t.append(h("b", "", value), h("span", "", label));
  return t;
}
/* Why a host is not green, in a few words: the number that crossed its limit. */
function reasons(host) {
  const out = [];
  if (!host.up) return ["not answering"];
  if (levelOf(host.cpu, 0.8, 0.95) !== "ok") out.push(`CPU ${pct(host.cpu)}%`);
  if (levelOf(host.mem, 0.85, 0.95) !== "ok") out.push(`RAM ${pct(host.mem)}%`);
  if (host.temp !== null && levelOf(host.temp, 70, 85) !== "ok") out.push(`${Math.round(host.temp)}°C`);
  for (const d of host.disks) if (d.status === "warn" || d.status === "crit") out.push(`${d.mount} ${pct(d.pct)}%`);
  return out;
}
function section(title) { return h("h2", "", title); }
function empty(text) { return h("div", "empty", text); }

/* ---------- screens ---------- */
const screens = {
  overview(s) {
    const out = [];
    if (!s.hosts.length) return [empty("No hosts reported")];
    const cards = h("div", "cards");
    for (const host of s.hosts) {
      const card = h("div", "card " + host.status);
      const head = h("div", "card-head");
      head.append(h("span", "name", host.name), h("span", "tag " + host.status, host.up ? LABEL[host.status] : "DOWN"));
      card.appendChild(head);
      const rings = h("div", "rings");
      rings.append(ring("CPU", host.cpu, levelOf(host.cpu, 0.8, 0.95)), ring("RAM", host.mem, levelOf(host.mem, 0.85, 0.95)));
      card.appendChild(rings);
      const facts = h("div", "facts");
      if (host.temp !== null) facts.appendChild(fact("Temp", Math.round(host.temp) + "°C"));
      facts.appendChild(fact("Up", span(host.uptime)));
      if (host.load1 !== null) facts.appendChild(fact("Load", host.load1.toFixed(2)));
      card.appendChild(facts);
      const why = reasons(host);
      if (why.length) card.appendChild(h("div", "why " + host.status, why.join(" · ")));
      if (host.rx_bps !== null) {
        const net = h("div", "facts");
        net.append(fact("↓", rate(host.rx_bps)), fact("↑", rate(host.tx_bps)));
        card.appendChild(net);
      }
      cards.appendChild(card);
    }
    out.push(cards);
    const glance = h("div", "summary");
    if (s.containers_known) {
      const running = s.containers.filter((c) => c.state === "running").length;
      const bad = s.containers.filter((c) => c.state !== "running" && c.state !== "exited").length;
      glance.appendChild(tile(`${running} / ${s.containers.length}`, "containers running", bad ? "crit" : "ok"));
    }
    if (s.services.length) {
      const up = s.services.filter((x) => x.ok).length;
      glance.appendChild(tile(`${up} / ${s.services.length}`, "services reachable", up === s.services.length ? "ok" : "crit"));
    }
    if (s.power_total !== null && s.power_total !== undefined) glance.appendChild(tile(Math.round(s.power_total) + " W", "power draw", "ok"));
    if (glance.children.length) out.push(glance);
    return out;
  },

  storage(s) {
    const disks = [];
    for (const host of s.hosts) for (const d of host.disks) disks.push({ host: host.name, ...d });
    disks.sort((a, b) => b.pct - a.pct);
    const rows = h("div", "rows");
    rows.dataset.fit = "1"; // fit() drops the rows that do not fit the screen
    for (const d of disks.slice(0, 60)) {
      const detail = h("div", "detail");
      detail.append(h("b", "", pct(d.pct) + "%"), ` ${bytes(d.used)} / ${bytes(d.total)}`);
      rows.appendChild(row(d.status, d.mount, d.host, d.pct, detail));
    }
    return [section("Disk space, fullest first"), rows];
  },

  network(s) {
    const left = h("div"), right = h("div");
    left.appendChild(section("Throughput"));
    const rows = h("div", "rows");
    const top = Math.max(1, ...s.hosts.map((x) => Math.max(x.rx_bps || 0, x.tx_bps || 0)));
    for (const host of s.hosts.filter((x) => x.rx_bps !== null)) {
      const detail = h("div", "detail");
      detail.append(h("b", "", "↓ " + rate(host.rx_bps)), h("br"), "↑ " + rate(host.tx_bps));
      rows.appendChild(row("ok", host.name, "", Math.min(1, ((host.rx_bps || 0) + (host.tx_bps || 0)) / (2 * top)), detail));
    }
    left.appendChild(rows.children.length ? rows : empty("No throughput data"));
    right.appendChild(section("Reachability"));
    const list = h("div", "rows");
    for (const sv of s.services) {
      const r = h("div", "row service " + sv.status);
      r.append(h("div", "label", sv.name), h("div", "dot " + sv.status, sv.ok ? "UP" : "DOWN"),
        h("div", "detail", sv.latency_ms === null ? "" : Math.round(sv.latency_ms) + " ms"));
      list.appendChild(r);
    }
    right.appendChild(s.services.length ? list : empty("No checks configured"));
    const two = h("div", "two");
    two.append(left, right);
    return [two];
  },

  containers(s) {
    const running = s.containers.filter((c) => c.state === "running").length;
    const problems = s.containers.filter((c) => c.state !== "running" && c.state !== "exited").length;
    const counters = h("div", "counters");
    for (const [n, label, cls] of [[running, "running", "ok"], [s.containers.length, "total", ""], [problems, "with problems", problems ? "crit" : "ok"]]) {
      const c = h("div", "counter");
      const b = h("b", cls, String(n));
      c.append(b, h("span", "", label));
      counters.appendChild(c);
    }
    const rank = { crit: 0, warn: 1, ok: 2, unknown: 3 };
    const list = [...s.containers].sort((a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name));
    const chips = h("div", "chips");
    for (const c of list.slice(0, 30)) {
      const chip = h("div", "chip " + c.status);
      chip.append(h("span", "n", c.name), h("span", "s", c.state === "running" && c.mem ? bytes(c.mem) : c.state));
      chips.appendChild(chip);
    }
    const out = [counters, chips];
    if (list.length > 30) out.push(h("div", "more", `+ ${list.length - 30} more`));
    return out;
  },

  power(s) {
    const out = [];
    const total = s.power_total;
    if (total !== null && total !== undefined) {
      const big = h("div", "power-total");
      big.append(h("b", "", Math.round(total)), h("span", "", "W now"));
      out.push(big);
      const rows = h("div", "rows");
      for (const p of s.power.filter((x) => x.watts !== null)) {
        const detail = h("div", "detail");
        detail.appendChild(h("b", "", Math.round(p.watts) + " W"));
        rows.appendChild(row("ok", p.name, "", total ? p.watts / total : 0, detail));
      }
      out.push(rows);
    }
    if (s.tiles.length) {
      const tiles = h("div", "tiles");
      for (const t of s.tiles) {
        const tile = h("div", "tile " + t.status);
        tile.append(h("b", "", t.value === null ? "--" : `${Math.round(t.value * 10) / 10}${t.unit ? " " + t.unit : ""}`), h("span", "", t.name));
        tiles.appendChild(tile);
      }
      out.push(tiles);
    }
    return out;
  },
};

function available(s) {
  const names = [];
  for (const name of cfg.screens) {
    if (name === "overview") names.push(name);
    else if (name === "storage" && s.hosts.some((x) => x.disks.length)) names.push(name);
    else if (name === "network" && (s.services.length || s.hosts.some((x) => x.rx_bps !== null))) names.push(name);
    else if (name === "containers" && s.containers_known) names.push(name);
    else if (name === "power" && (s.power.length || s.tiles.length)) names.push(name);
  }
  return names.length ? names : ["overview"];
}

/* ---------- drawing ---------- */
function draw() {
  const stale = !snap || failed || (snap.age !== null && snap.age > Math.max(15, cfg.interval * 4));
  const status = stale ? "unknown" : snap.status;
  const pill = $("pill");
  pill.className = "pill " + status;
  pill.textContent = LABEL[status];
  $("title").textContent = cfg.title;
  $("age").textContent = snap && snap.age !== null ? `updated ${Math.round(snap.age)} s ago` : "";

  const banner = $("banner");
  banner.hidden = !(stale || (snap && snap.problems.length));
  banner.textContent = stale ? "No fresh data from the server: retrying" : "Source problem: " + snap.problems[0];

  const alerts = $("alerts");
  alerts.hidden = !(snap && snap.alerts.length);
  alerts.replaceChildren();
  if (snap && snap.alerts.length) {
    alerts.className = snap.alerts.some((a) => a.severity === "critical") ? "crit" : "";
    for (const a of snap.alerts.slice(0, 4)) {
      const item = h("span");
      item.append(h("b", "", a.name), a.summary ? " " + a.summary : "");
      alerts.appendChild(item);
    }
  }
  if (!snap) {
    $("screen").replaceChildren(empty("Waiting for data…"));
    return;
  }
  const names = available(snap);
  if (pinned && names.includes(pinned)) screenIndex = names.indexOf(pinned);
  else if (screenIndex >= names.length) screenIndex = 0;
  const name = names[screenIndex];
  $("screen").replaceChildren(...screens[name](snap));
  fit();
  const dots = $("dots");
  dots.replaceChildren(...names.map((n) => h("span", n === name ? "on" : "", n)));
}

// A list that is longer than the screen loses its last rows instead of running off the bottom.
function fit() {
  const main = $("screen");
  for (const rows of main.querySelectorAll(".rows[data-fit]")) {
    const total = rows.children.length;
    let shown = total;
    let more = null;
    while (main.scrollHeight > main.clientHeight + 1 && shown > 1) {
      rows.lastElementChild.remove();
      shown -= 1;
      if (!more) {
        more = h("div", "more", "");
        rows.after(more);
      }
      more.textContent = `+ ${total - shown} more, the fullest are shown`;
    }
  }
}

function next(step) {
  if (!snap) return;
  const names = available(snap);
  screenIndex = (screenIndex + step + names.length) % names.length;
  pinned = null;
  shownAt = Date.now();
  draw();
}

function tick() {
  $("clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const seconds = Number(params.get("rotate")) || cfg.rotate_seconds;
  const elapsed = (Date.now() - shownAt) / 1000;
  $("progress").firstElementChild.style.width = pinned ? "0" : Math.min(100, (elapsed / seconds) * 100) + "%";
  if (!pinned && elapsed >= seconds) next(1);
}

async function api(path) {
  const response = await fetch(path, { headers: token ? { Authorization: "Bearer " + token } : {}, cache: "no-store" });
  if (!response.ok) throw new Error(path + " " + response.status);
  return response.json();
}

async function poll() {
  try {
    snap = await api("/api/stats");
    failed = false;
  } catch (error) {
    failed = true;
  }
  draw();
}

async function start() {
  try { cfg = { ...cfg, ...(await api("/api/config")) }; } catch (error) { /* keep the defaults */ }
  document.title = cfg.title;
  await poll();
  setInterval(poll, Math.max(2000, (cfg.interval * 1000) / 2));
  setInterval(tick, 500);
  // A fixed picture burns into an always-on panel: nudge everything a few pixels every minute.
  setInterval(() => {
    const dx = Math.round(Math.random() * 6 - 3), dy = Math.round(Math.random() * 6 - 3);
    $("frame").style.transform = `translate(${dx}px, ${dy}px)`;
  }, 60000);
}

document.addEventListener("click", () => next(1));
document.addEventListener("keydown", (e) => { if (e.key === "ArrowRight") next(1); else if (e.key === "ArrowLeft") next(-1); });
document.addEventListener("mousemove", () => { document.body.classList.add("pointer"); });
start();
