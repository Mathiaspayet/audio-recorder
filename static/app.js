/* =========================================================================
   Moniteur Audio  -  logique du tableau de bord
   ========================================================================= */

"use strict";

// Arrêts de l'échelle de couleur : calme -> bruit fort (doit suivre style.css)
const SCALE = ["#16282d", "#2f7d6f", "#d39a2c", "#e44a2a"];

let CONFIG   = { segment_minutes: 10, retention_days: 3,
                 quiet_db: -50, loud_db: -15, recording: false, folder: "" };
let SEGMENTS = [];
let STORAGE  = null;     // dernier état du disque connu
let selectedName = null;

const $ = (id) => document.getElementById(id);

/* ---------- Couleurs ----------------------------------------------------- */

function hexToRgb(h) {
  return [parseInt(h.slice(1, 3), 16),
          parseInt(h.slice(3, 5), 16),
          parseInt(h.slice(5, 7), 16)];
}
function mix(a, b, t) {
  const A = hexToRgb(a), B = hexToRgb(b);
  return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(",")})`;
}
function colorFor(db) {
  const q = CONFIG.quiet_db, l = CONFIG.loud_db;
  let t = (db - q) / (l - q);
  t = Math.max(0, Math.min(1, t));
  const seg = t * (SCALE.length - 1);
  const i   = Math.min(Math.floor(seg), SCALE.length - 2);
  return mix(SCALE[i], SCALE[i + 1], seg - i);
}
function heightFor(db) {
  return Math.max(0.03, Math.min(1, (db + 65) / 60));
}

/* ---------- Formatage ---------------------------------------------------- */

function parseStart(s) {
  const [d, t] = s.split("T");
  const [Y, M, D] = d.split("-").map(Number);
  const [h, mi]   = t.split(":").map(Number);
  return { key: d, date: new Date(Y, M - 1, D), hhmm: t.slice(0, 5),
           minutes: h * 60 + mi };
}
function dayLabel(date) {
  return date.toLocaleDateString("fr-FR",
         { weekday: "long", day: "numeric", month: "long" });
}
function hhmm(totalMin) {
  const h = Math.floor(totalMin / 60) % 24, m = totalMin % 60;
  return String(h).padStart(2, "0") + ":" + String(m).padStart(2, "0");
}
function humanDuration(ms) {
  const min = Math.round(ms / 60000);
  if (min < 60) return min + " min";
  const h = Math.floor(min / 60), d = Math.floor(h / 24);
  if (d >= 1) return d + " j " + (h % 24) + " h";
  return h + " h " + (min % 60) + " min";
}
function fmtBytes(b) {
  if (b >= 1e12) return (b / 1e12).toFixed(2) + " To";
  if (b >= 1e9)  return (b / 1e9).toFixed(2) + " Go";
  if (b >= 1e6)  return (b / 1e6).toFixed(0) + " Mo";
  return (b / 1e3).toFixed(0) + " Ko";
}

/* ---------- Tableau de bord --------------------------------------------- */

async function fetchData() {
  try {
    const res  = await fetch("/api/segments", { cache: "no-store" });
    const data = await res.json();
    CONFIG   = data.config;
    SEGMENTS = data.segments;
    render();
  } catch (err) {
    $("emptyMsg").textContent =
      "Impossible de contacter le serveur. Réessai automatique…";
  }
}

function render() {
  $("statCount").textContent = SEGMENTS.length;
  $("liveDot").classList.toggle("live", CONFIG.recording);
  $("statRec").textContent =
    CONFIG.recording ? "enregistrement actif" : "à l'arrêt";
  $("legendNote").textContent =
    `dossier « ${CONFIG.folder} »  ·  échelle ${CONFIG.quiet_db} → `
    + `${CONFIG.loud_db} dB  ·  conservation ${CONFIG.retention_days} j`;

  if (SEGMENTS.length === 0) {
    $("statSpan").textContent = "—";
    $("timeline").innerHTML =
      `<p class="empty">En attente du premier segment…<br>` +
      `Le premier fichier apparaît après environ ` +
      `${CONFIG.segment_minutes} minutes d'enregistrement.<br>` +
      `Pensez à renseigner l'adresse RTSP dans les réglages (icône en haut).</p>`;
    return;
  }

  const first = new Date(SEGMENTS[0].start);
  const last  = new Date(SEGMENTS[SEGMENTS.length - 1].start);
  $("statSpan").textContent = humanDuration(last - first);

  const days = {};
  for (const seg of SEGMENTS) {
    const p = parseStart(seg.start);
    (days[p.key] = days[p.key] || { date: p.date, segs: [] })
      .segs.push({ seg, p });
  }
  const keys = Object.keys(days).sort().reverse();

  const tl = $("timeline");
  tl.innerHTML = "";
  const gapThreshold = CONFIG.segment_minutes * 1.8;

  for (const key of keys) {
    const day = days[key];

    const block = document.createElement("div");
    block.className = "day";

    const head = document.createElement("div");
    head.className = "day-head";
    head.innerHTML =
      `<span class="day-name">${dayLabel(day.date)}</span>` +
      `<span class="day-meta">${day.segs.length} segments</span>`;
    block.appendChild(head);

    const strip = document.createElement("div");
    strip.className = "strip";

    let prevMin = null;
    for (const { seg, p } of day.segs) {
      if (prevMin !== null && p.minutes - prevMin > gapThreshold) {
        const gap = document.createElement("div");
        gap.className = "cell gap";
        gap.title = "Interruption de l'enregistrement";
        strip.appendChild(gap);
      }
      prevMin = p.minutes;

      const cell = document.createElement("div");
      cell.className = "cell";
      cell.style.background = colorFor(seg.peak_db);
      cell.title = `${p.hhmm}  ·  pic ${seg.peak_db} dB`;
      cell.dataset.name = seg.name;
      if (seg.name === selectedName) cell.classList.add("selected");
      cell.addEventListener("click", () => selectSegment(seg.name));
      strip.appendChild(cell);
    }

    block.appendChild(strip);
    tl.appendChild(block);
  }

  if (selectedName === null) {
    selectSegment(SEGMENTS[SEGMENTS.length - 1].name);
  }
}

function selectSegment(name) {
  const seg = SEGMENTS.find((s) => s.name === name);
  if (!seg) return;
  selectedName = name;

  document.querySelectorAll(".cell.selected")
          .forEach((c) => c.classList.remove("selected"));
  const cell = document.querySelector(`.cell[data-name="${name}"]`);
  if (cell) cell.classList.add("selected");

  const p   = parseStart(seg.start);
  const end = hhmm(p.minutes + CONFIG.segment_minutes);

  $("player").hidden = false;
  $("selDate").textContent = dayLabel(p.date);
  $("selTime").textContent = `${p.hhmm} – ${end}   (${fmtBytes(seg.size)})`;
  $("selPeak").textContent = seg.peak_db;
  $("selMean").textContent = seg.mean_db;

  drawCurve(seg.curve);

  const audio = $("audio");
  audio.src = "/audio/" + encodeURIComponent(name);
  audio.load();
  audio.play().catch(() => {});

  $("playhead").style.display = "block";
  $("playhead").style.left = "8px";
}

function drawCurve(curve) {
  const box = $("curve");
  box.querySelectorAll(".curve-bar").forEach((b) => b.remove());
  const playhead = $("playhead");
  (curve || []).forEach((db) => {
    const bar = document.createElement("div");
    bar.className = "curve-bar";
    bar.style.height = (heightFor(db) * 100) + "%";
    bar.style.background = colorFor(db);
    box.insertBefore(bar, playhead);
  });
}

const audio = $("audio");
audio.addEventListener("timeupdate", () => {
  if (!audio.duration) return;
  const frac = audio.currentTime / audio.duration;
  $("playhead").style.left = `calc(8px + ${frac} * (100% - 16px))`;
});

/* ---------- Fenêtre de réglages ----------------------------------------- */

async function openSettings() {
  try {
    const [setRes, foldRes] = await Promise.all([
      fetch("/api/settings", { cache: "no-store" }),
      fetch("/api/folders",  { cache: "no-store" }),
    ]);
    const data    = await setRes.json();
    const folders = await foldRes.json();
    const s = data.settings;
    STORAGE = data.storage;

    $("fRtsp").value      = s.rtsp_url;
    $("fFolder").value    = s.folder;
    $("fSegment").value   = s.segment_minutes;
    $("fRetention").value = s.retention_days;
    $("fBitrate").value   = String(s.bitrate_kbps);
    $("fQuiet").value     = s.quiet_db;
    $("fLoud").value      = s.loud_db;

    $("folderList").innerHTML =
      folders.map((f) => `<option value="${f}"></option>`).join("");

    syncRangeOutputs();
    updateEstimate();
    $("modalMsg").textContent = "";
    $("modal").hidden = false;
  } catch (err) {
    alert("Impossible de charger les réglages.");
  }
}

function closeSettings() { $("modal").hidden = true; }

function syncRangeOutputs() {
  $("fSegmentOut").textContent   = $("fSegment").value + " min";
  $("fRetentionOut").textContent = $("fRetention").value + " j";
}

// Recalcule en direct l'estimation d'espace à partir des valeurs du formulaire.
function updateEstimate() {
  const kbps = Number($("fBitrate").value);
  const days = Number($("fRetention").value);
  const estimate = kbps * 1000 / 8 * days * 86400;   // octets

  $("stEstimate").textContent = fmtBytes(estimate);

  if (STORAGE) {
    // L'espace réellement disponible = libre + ce que le dossier occupe déjà
    // (puisque les anciens fichiers seront remplacés au fil de l'eau).
    const available = STORAGE.disk_free + STORAGE.current_usage;
    $("stFree").textContent  = fmtBytes(STORAGE.disk_free);
    $("stUsage").textContent = fmtBytes(STORAGE.current_usage);

    const ratio = available > 0 ? estimate / available : 1;
    const fill  = $("stFill");
    fill.style.width = Math.min(100, ratio * 100).toFixed(1) + "%";

    const verdict = $("stVerdict");
    verdict.className = "storage-verdict";
    if (ratio < 0.8) {
      fill.style.background = "var(--accent)";
      verdict.classList.add("ok");
      verdict.textContent = "L'espace disponible est largement suffisant.";
    } else if (ratio < 1) {
      fill.style.background = "var(--warn)";
      verdict.classList.add("warn");
      verdict.textContent =
        "Ça tient, mais l'espace libre deviendra juste. Réduisez la durée "
        + "de conservation ou la qualité si besoin.";
    } else {
      fill.style.background = "var(--danger)";
      verdict.classList.add("bad");
      verdict.textContent =
        "L'estimation dépasse l'espace disponible. Réduisez la conservation "
        + "ou la qualité, ou choisissez un disque plus grand.";
    }
  }
}

async function saveSettings() {
  if (!$("fRtsp").value.trim()) {
    $("modalMsg").textContent = "L'adresse RTSP est obligatoire.";
    return;
  }
  if ($("fQuiet").value === "" || $("fLoud").value === "") {
    $("modalMsg").textContent = "Les seuils dB sont obligatoires.";
    return;
  }

  const btn = $("saveSettings");
  btn.disabled = true;
  $("modalMsg").textContent = "Enregistrement…";

  const payload = {
    rtsp_url:        $("fRtsp").value,
    folder:          $("fFolder").value,
    segment_minutes: Number($("fSegment").value),
    retention_days:  Number($("fRetention").value),
    bitrate_kbps:    Number($("fBitrate").value),
    quiet_db:        Number($("fQuiet").value),
    loud_db:         Number($("fLoud").value),
  };

  try {
    const res  = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    STORAGE = data.storage;
    selectedName = null;        // le dossier a pu changer : on repart à zéro
    closeSettings();
    fetchData();
  } catch (err) {
    $("modalMsg").textContent = "Échec de l'enregistrement. Réessayez.";
  } finally {
    btn.disabled = false;
  }
}

/* ---------- Branchements ------------------------------------------------- */

$("openSettings").addEventListener("click", openSettings);
$("closeSettings").addEventListener("click", closeSettings);
$("cancelSettings").addEventListener("click", closeSettings);
$("saveSettings").addEventListener("click", saveSettings);
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) closeSettings();   // clic en dehors = fermer
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("modal").hidden) closeSettings();
});
$("fSegment").addEventListener("input", syncRangeOutputs);
$("fRetention").addEventListener("input", () => { syncRangeOutputs(); updateEstimate(); });
$("fBitrate").addEventListener("change", updateEstimate);

/* ---------- Version ------------------------------------------------------ */

async function fetchVersion() {
  try {
    const res  = await fetch("/api/version", { cache: "no-store" });
    const data = await res.json();
    if (!data.build_date) return;
    const d = new Date(data.build_date);
    const label = d.toLocaleString("fr-FR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
    const el = document.createElement("span");
    el.className = "version";
    el.textContent = "v " + label;
    $("stats").after(el);
  } catch (_) {}
}

/* ---------- Démarrage ---------------------------------------------------- */

fetchData();
fetchVersion();
setInterval(fetchData, 45000);
