const COLORS = {
  blocked: "#ff5a3c",
  likely: "#ff8a4a",
  watch: "#e6b325",
  clear: "#3d4a57",
  naive: "#7aa2ff",
  safe: "#2fd3c3",
};

// "Is the site under water" and "can a vehicle still get there" are different
// questions. The sidebar has to answer both or it reads as a contradiction.
const ROAD_ACCESS = {
  clear: "all approach roads open",
  degraded: "some approach roads flooded",
  cut_off: "no dry road reaches it",
};

const map = L.map("map", { zoomControl: true });
const tileOpts = { attribution: "&copy; OpenStreetMap &copy; CARTO", maxZoom: 19 };
let tileLayer = L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", tileOpts).addTo(map);

const layers = {
  floods: L.layerGroup().addTo(map),
  roads: L.layerGroup().addTo(map),
  spots: L.layerGroup().addTo(map),
  facilities: L.layerGroup().addTo(map),
  route: L.layerGroup().addTo(map),
  picks: L.layerGroup().addTo(map),
  zones: L.layerGroup().addTo(map),
};
// Feature 1 overlay reads JalMarg.map. Feature 2 should Object.assign, not replace.
window.JalMarg = Object.assign(window.JalMarg || {}, { map, layers });

let meta = null;
let clickMode = "origin";
let origin = null;
let dest = null;
let routeResult = null;
let selectedRouteId = null;
let prefer = "balanced";
let useZones = false;
let originName = "Origin";
let destName = "Destination";
let scenarioData = null;

const originInput = document.getElementById("originInput");
const destInput = document.getElementById("destInput");
const placeOptions = document.getElementById("placeOptions");
const themeToggle = document.getElementById("themeToggle");
const liveLocation = document.getElementById("liveLocation");
const locationStatus = document.getElementById("locationStatus");

const OPTION_COLORS = ["#2fd3c3", "#7aa2ff", "#e6b325", "#c08bff", "#ff8a4a"];

const rainEl = document.getElementById("rain");
const rainValue = document.getElementById("rainValue");
const statsEl = document.getElementById("stats");
const facilityList = document.getElementById("facilityList");
const routeBox = document.getElementById("routeBox");
const presetEl = document.getElementById("preset");
const disclaimer = document.getElementById("disclaimer");
const updatedAt = document.getElementById("updatedAt");
const liveRainNote = document.getElementById("liveRainNote");
const simModeBtn = document.getElementById("simModeBtn");
const liveModeBtn = document.getElementById("liveModeBtn");
const simControls = document.getElementById("simControls");
const weatherPanel = document.getElementById("weatherPanel");
const weatherList = document.getElementById("weatherList");
const weatherStamp = document.getElementById("weatherStamp");
const weatherMode = document.getElementById("weatherMode");
const rerouteNote = document.getElementById("rerouteNote");
const clockLabel = document.getElementById("clockLabel");

const REROUTE_MM = 8;
let zonePoll = null;
let lastZoneFingerprint = null;
let lastRouteSignature = null;

function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("jalMargTheme", next);
  const light = next === "light";
  if (themeToggle) {
    themeToggle.setAttribute("aria-label", light ? "Switch to dark mode" : "Switch to light mode");
    themeToggle.title = light ? "Switch to dark mode" : "Switch to light mode";
    themeToggle.classList.toggle("is-light", light);
  }
  tileLayer.setUrl(
    light
      ? "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      : "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
  );
}

function rainMm() {
  return Number(rainEl.value);
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function getJson(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

function fillPlaceList(extra) {
  if (!placeOptions) return;
  const seen = new Set();
  placeOptions.innerHTML = "";
  const rows = (meta && meta.nodes ? meta.nodes.map((n) => n.name) : []).concat(extra || []);
  rows.forEach((name) => {
    if (!name || seen.has(name)) return;
    seen.add(name);
    const opt = document.createElement("option");
    opt.value = name;
    placeOptions.appendChild(opt);
  });
}

function landmarkByName(value) {
  const q = (value || "").trim().toLowerCase();
  if (!q || !meta) return null;
  return meta.nodes.find((n) => n.name.toLowerCase() === q) || null;
}

function setPoint(kind, point, name) {
  if (kind === "origin") {
    origin = point;
    originName = name || (originInput ? originInput.value.trim() : "") || originName;
    if (originInput) originInput.value = originName;
  } else {
    dest = point;
    destName = name || (destInput ? destInput.value.trim() : "") || destName;
    if (destInput) destInput.value = destName;
  }
  syncPresetDropdown();
  drawPicks();
}

function zoneColor(mm, status) {
  if (status === "unavailable" || mm == null) return "#8b98a5";
  if (status === "stale") return "#c4a35a";
  if (mm < 8) return "#7aa2ff";
  if (mm < 25) return "#e6b325";
  if (mm < 50) return "#ff8a4a";
  return "#ff5a3c";
}

function zoneFingerprint(zones) {
  return (zones || []).map((z) => `${z.id}:${z.status}:${z.rain_mm}`).join("|");
}

function maxRainDelta(prevFp, zones) {
  if (!prevFp) return 0;
  const prev = {};
  prevFp.split("|").forEach((bit) => {
    const [id, , mm] = bit.split(":");
    prev[id] = mm === "null" || mm === "undefined" ? null : Number(mm);
  });
  let best = 0;
  (zones || []).forEach((z) => {
    const a = prev[z.id];
    const b = z.rain_mm;
    if (a == null || b == null) {
      if (a !== b) best = Math.max(best, REROUTE_MM);
      return;
    }
    best = Math.max(best, Math.abs(a - b));
  });
  return best;
}

function selectedPathZones() {
  if (!useZones) return [];
  const opt = (routeResult && routeResult.options || []).find((o) => o.id === selectedRouteId)
    || (routeResult && routeResult.options && routeResult.options[0]);
  const along = (opt && opt.weather_along) || [];
  if (!along.length) return [];
  const byId = {};
  ((scenarioData && scenarioData.zones) || []).forEach((z) => {
    byId[z.id] = z;
  });
  return along.map((a) => Object.assign({}, byId[a.id] || {}, a));
}

function drawZones(zones) {
  layers.zones.clearLayers();
  if (!useZones) return;
  (zones || []).forEach((z) => {
    const status = z.status || (z.ok ? "ok" : "unavailable");
    const color = zoneColor(z.rain_mm, status);
    const mm = z.rain_mm == null ? "unavailable" : `${z.rain_mm} mm`;
    const bounds = z.bounds || (z.south != null
      ? [[z.south, z.west], [z.north, z.east]]
      : null);
    const layer = bounds
      ? L.rectangle(bounds, {
          color,
          weight: 2,
          fillColor: color,
          fillOpacity: 0.22,
        })
      : L.circle([z.lat, z.lon], {
          radius: 4000,
          color,
          weight: 2,
          fillColor: color,
          fillOpacity: 0.18,
        });
    layer
      .bindTooltip(`<b>${z.name}</b><br>${mm}`, {
        sticky: true,
        opacity: 0.95,
        className: "zone-tip",
      })
      .bindPopup(`<b>${z.name}</b><br>${mm}<br>status: ${status}`)
      .addTo(layers.zones);
  });
}

function drawPathZones() {
  drawZones(selectedPathZones());
}

function markRainMode(live) {
  useZones = Boolean(live);
  if (simModeBtn) {
    simModeBtn.classList.toggle("is-active", !useZones);
    simModeBtn.setAttribute("aria-pressed", useZones ? "false" : "true");
  }
  if (liveModeBtn) {
    liveModeBtn.classList.toggle("is-active", useZones);
    liveModeBtn.setAttribute("aria-pressed", useZones ? "true" : "false");
  }
  if (simControls) simControls.classList.toggle("is-standby", useZones);
}

function renderWeatherPanel(data) {
  if (!weatherPanel) return;
  if (!useZones) {
    weatherPanel.hidden = true;
    if (clockLabel) clockLabel.textContent = "simulation";
    markRainMode(false);
    return;
  }
  weatherPanel.hidden = false;
  const stale = data.zones_stale;
  const ok = data.zones_ok;
  if (weatherMode) {
    weatherMode.textContent = stale ? "STALE" : ok ? "LIVE" : "UNAVAILABLE";
    weatherMode.className = `mode-badge${stale ? " is-stale" : ok ? "" : " is-bad"}`;
  }
  if (weatherStamp) {
    const when = data.zones_fetched_at || data.updated_at;
    weatherStamp.textContent = `${data.zones_source || "Open-Meteo"} · ${fmtTime(when)}`;
  }
  if (clockLabel) clockLabel.textContent = stale ? "stale weather" : "live weather";
  const pathZones = selectedPathZones();
  const rows = pathZones.length ? pathZones : [];
  if (weatherList) {
    weatherList.innerHTML = rows.length
      ? rows
          .map((z) => {
            const status = z.status || (z.ok ? "ok" : "unavailable");
            const mm = z.rain_mm == null ? "—" : `${z.rain_mm} mm`;
            return `<li><span class="swatch" style="background:${zoneColor(z.rain_mm, status)}"></span><b>${z.name}</span> ${mm} <small>${status}</small></li>`;
          })
          .join("")
      : `<li>Squares appear on the map once a route is found — only cells the path crosses.</li>`;
  }
}

function popupHtml(spot) {
  const reasons = (spot.reasons || []).map((r) => `<li>${r}</li>`).join("");
  return `<h3>${spot.name}</h3>
    <div>${spot.area} · risk ${(spot.risk * 100).toFixed(0)}% · ${spot.level}</div>
    <ul>${reasons}</ul>
    <div style="color:#8b98a5">${spot.source}</div>
    <p>${spot.notes}</p>`;
}

function drawScenario(data) {
  layers.floods.clearLayers();
  layers.roads.clearLayers();
  layers.spots.clearLayers();
  layers.facilities.clearLayers();

  for (const e of data.edges) {
    if (e.level === "clear") continue;
    L.polyline(e.coords, {
      color: COLORS[e.level],
      weight: e.blocked ? 6 : 4,
      opacity: 0.85,
    })
      .bindPopup(`<b>${e.name}</b><br>${e.level}${e.near_hotspots.length ? "<br>" + e.near_hotspots.join(", ") : ""}`)
      .addTo(layers.roads);
  }

  for (const s of data.hotspots) {
    if (s.radius_m > 0) {
      L.circle([s.lat, s.lon], {
        radius: s.radius_m,
        color: COLORS[s.level],
        fillColor: COLORS[s.level],
        fillOpacity: 0.12,
        weight: 1,
      }).addTo(layers.floods);
    }
    L.circleMarker([s.lat, s.lon], {
      radius: 7,
      color: "#101418",
      weight: 1,
      fillColor: COLORS[s.level],
      fillOpacity: 1,
    })
      .bindPopup(popupHtml(s))
      .addTo(layers.spots);
  }

  for (const f of data.facilities) {
    const color =
      f.status === "cut_off" ? COLORS.blocked : f.status === "at_risk" ? COLORS.likely : COLORS.safe;
    const marker = L.circleMarker([f.lat, f.lon], {
      radius: f.kind === "hospital" ? 6 : 5,
      color,
      fillColor: "#101418",
      fillOpacity: 1,
      weight: 2,
    }).bindPopup(
      `<h3>${f.name}</h3><div>${f.kind.replace("_", " ")} · ${f.status_label}</div>
       <ul><li>Site: ${f.site_flooded ? "inside a flood radius" : "not in a flood radius"}</li>
       <li>Road access: ${ROAD_ACCESS[f.road_access]} (${f.flooded_approaches}/${f.approach_count} approaches flooded)</li></ul>
       <p>${f.notes}</p>`
    );
    marker.addTo(layers.facilities);
  }

  statsEl.innerHTML = `
    <li>Blocked spots <b>${data.counts.blocked}</b></li>
    <li>Likely / watch <b>${data.counts.likely} / ${data.counts.watch}</b></li>
    <li>Roads blocked <b>${data.counts.roads_blocked}</b></li>
    <li>Facility sites flooded <b>${data.counts.facilities_site_flooded}</b></li>
    <li>Unreachable by road <b>${data.counts.facilities_cut_off}</b></li>
  `;

  const trouble = data.facilities.filter((f) => f.status !== "open");
  facilityList.innerHTML = trouble.length
    ? trouble
        .map(
          (f) =>
            `<li class="${f.status}"><div class="kind">${f.kind.replace("_", " ")} · ${f.status_label}</div>${f.name}</li>`
        )
        .join("")
    : `<li>None at this rainfall.</li>`;

  disclaimer.textContent = data.disclaimer;
  updatedAt.textContent = fmtTime(data.updated_at);
  scenarioData = data;
  drawPathZones();
  renderWeatherPanel(data);
}

function nodeLatLng(nodeId) {
  const n = meta.nodes.find((x) => x.id === nodeId);
  return n ? { lat: n.lat, lon: n.lon, node: n.id } : null;
}

function syncPresetDropdown() {
  if (!presetEl || !meta || !meta.presets) return;
  const oName = (originName || (originInput ? originInput.value : "") || "").trim();
  const dName = (destName || (destInput ? destInput.value : "") || "").trim();

  const matchedPreset = meta.presets.find((p) => {
    const pOrigin = nodeLatLng(p.origin.node);
    const pDest = nodeLatLng(p.dest.node);
    const pOriginName = (meta.nodes.find((n) => n.id === p.origin.node)?.name || p.origin.name || "").trim().toLowerCase();
    const pDestName = (meta.nodes.find((n) => n.id === p.dest.node)?.name || p.dest.name || "").trim().toLowerCase();

    const originMatches = (origin && pOrigin && Math.abs(origin.lat - pOrigin.lat) < 0.0001 && Math.abs(origin.lon - pOrigin.lon) < 0.0001) || (oName && oName.toLowerCase() === pOriginName);
    const destMatches = (dest && pDest && Math.abs(dest.lat - pDest.lat) < 0.0001 && Math.abs(dest.lon - pDest.lon) < 0.0001) || (dName && dName.toLowerCase() === pDestName);
    return originMatches && destMatches;
  });

  let customOpt = presetEl.querySelector("option[value='custom']");
  if (matchedPreset) {
    if (customOpt) customOpt.remove();
    presetEl.value = matchedPreset.id;
  } else {
    const oLabel = oName || (origin ? `${origin.lat.toFixed(3)}, ${origin.lon.toFixed(3)}` : "Origin");
    const dLabel = dName || (dest ? `${dest.lat.toFixed(3)}, ${dest.lon.toFixed(3)}` : "Destination");
    if (!customOpt) {
      customOpt = document.createElement("option");
      customOpt.value = "custom";
      presetEl.insertBefore(customOpt, presetEl.firstChild);
    }
    customOpt.textContent = `Ambulance: ${oLabel} → ${dLabel}`;
    presetEl.value = "custom";
  }
}

function drawPicks() {
  layers.picks.clearLayers();
  if (origin) {
    const oLabel = originName || (originInput ? originInput.value.trim() : "") || "Origin";
    L.marker([origin.lat, origin.lon], { title: oLabel })
      .bindTooltip(oLabel, { permanent: true, direction: "top", offset: [0, -10] })
      .addTo(layers.picks);
  }
  if (dest) {
    const dLabel = destName || (destInput ? destInput.value.trim() : "") || "Destination";
    L.marker([dest.lat, dest.lon], { title: dLabel })
      .bindTooltip(dLabel, { permanent: true, direction: "top", offset: [0, -10] })
      .addTo(layers.picks);
  }
}

function applyPreset() {
  if (presetEl.value === "custom") return;
  const p = meta.presets.find((x) => x.id === presetEl.value);
  if (!p) return;
  origin = nodeLatLng(p.origin.node);
  dest = nodeLatLng(p.dest.node);
  originName = (origin && meta.nodes.find((n) => n.id === p.origin.node)?.name) || p.origin.name || "Origin";
  destName = (dest && meta.nodes.find((n) => n.id === p.dest.node)?.name) || p.dest.name || "Destination";
  if (originInput) originInput.value = originName;
  if (destInput) destInput.value = destName;
  const customOpt = presetEl.querySelector("option[value='custom']");
  if (customOpt) customOpt.remove();
  drawPicks();
}

async function loadScenario() {
  rainValue.textContent = String(rainMm());
  const data = await getJson(`/api/scenario?rain_mm=${rainMm()}&use_zones=${useZones ? "true" : "false"}`);
  drawScenario(data);
}

function roadTypesLine(types) {
  if (!types) return "";
  const order = ["highway", "arterial", "local", "other"];
  const bits = order
    .filter((k) => types[k])
    .map((k) => `${types[k]}% ${k}`);
  return bits.length ? bits.join(" · ") : "";
}

function drawRouteOptions(result, activeId) {
  layers.route.clearLayers();
  const options = result.options || [];
  if (!options.length && result.naive) {
    L.polyline(result.naive.coords, {
      color: COLORS.naive,
      weight: 4,
      dashArray: "8 8",
      opacity: 0.95,
    }).addTo(layers.route);
    map.fitBounds(L.polyline(result.naive.coords).getBounds(), { padding: [40, 40] });
    return;
  }

  let activeBounds = null;
  options.forEach((opt, i) => {
    const selected = opt.id === activeId;
    const color = selected ? COLORS.safe : OPTION_COLORS[i % OPTION_COLORS.length];
    const line = L.polyline(opt.coords, {
      color,
      weight: selected ? 7 : 3,
      opacity: selected ? 0.98 : 0.45,
      dashArray: selected ? null : "6 8",
    }).addTo(layers.route);
    if (selected) activeBounds = line.getBounds();
  });
  if (activeBounds) map.fitBounds(activeBounds, { padding: [40, 40] });
}

function renderRouteBox(result) {
  const options = result.options || [];
  const displayOrigin = originName || (originInput ? originInput.value.trim() : "") || result.origin_name || "Origin";
  const displayDest = destName || (destInput ? destInput.value.trim() : "") || result.dest_name || "Destination";
  const head = `<strong>${displayOrigin} → ${displayDest}</strong>`;

  if (result.unreachable && !options.some((o) => !o.uses_flooded_roads)) {
    const floodBits = (result.naive && result.naive.flooded_segments.length)
      ? result.naive.flooded_segments.join("; ")
      : "none on shortest path";
    routeBox.innerHTML = `${head}
      <div>Fastest known path: ${result.naive.km} km · ${result.naive.minutes} min</div>
      <div class="bad">Flooded segments: ${floodBits}</div>
      <div class="bad">No dry path on the available road network. ${result.unreachable_reason || ""}</div>`;
    return;
  }

  if (!options.length) {
    routeBox.innerHTML = `${head}<div class="bad">No route options found.</div>`;
    return;
  }

  const cards = options
    .map((opt, i) => {
      const selected = opt.id === selectedRouteId;
      const rec = opt.recommended ? `<span class="rec">Recommended</span>` : "";
      const wet = opt.uses_flooded_roads ? `<span class="tag bad-tag">uses flooded roads</span>` : `<span class="tag ok-tag">dry</span>`;
      const types = roadTypesLine(opt.road_types);
      const via = opt.via && opt.via.length ? `via ${opt.via.slice(0, 3).join(" → ")}` : "";
      const notes = (opt.safety_notes || []).slice(0, 1).join(" ");
      const weather = (opt.weather_along || [])
        .map((z) => `${z.name} ${z.rain_mm == null ? "?" : z.rain_mm + " mm"}`)
        .join(" → ");
      return `<button type="button" class="route-opt${selected ? " is-selected" : ""}${opt.recommended ? " is-recommended" : ""}" data-route-id="${opt.id}" style="--opt-accent:${OPTION_COLORS[i % OPTION_COLORS.length]}">
        <div class="route-opt-top"><span class="route-opt-label">${opt.label}</span>${rec}${wet}</div>
        <div class="route-opt-metrics">
          <span>${opt.minutes} min</span>
          <span>${opt.km} km</span>
          <span>safety ${opt.safety_score}</span>
        </div>
        <div class="route-opt-meta">${types}</div>
        <div class="route-opt-meta">${via}</div>
        ${weather ? `<div class="route-opt-meta">Rain along path: ${weather}</div>` : ""}
        <div class="route-opt-note">${notes}</div>
      </button>`;
    })
    .join("");

  routeBox.innerHTML = `${head}
    <p class="route-hint">Prefer: ${result.prefer}. Click a route to select it on the map.</p>
    <div class="route-opts">${cards}</div>`;

  routeBox.querySelectorAll("[data-route-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedRouteId = btn.getAttribute("data-route-id");
      drawRouteOptions(result, selectedRouteId);
      renderRouteBox(result);
      drawPathZones();
      renderWeatherPanel(scenarioData || {});
    });
  });
}

async function computeRoute() {
  if (originInput && originInput.value.trim() && (!origin || originName !== originInput.value.trim())) {
    await applyTypedPlace("origin");
  }
  if (destInput && destInput.value.trim() && (!dest || destName !== destInput.value.trim())) {
    await applyTypedPlace("dest");
  }
  if (!origin || !dest) {
    routeBox.innerHTML = "Set origin and destination first.";
    return;
  }
  routeBox.textContent = "Finding route options…";
  const oPayload = Object.assign({}, origin, { name: originName || (originInput ? originInput.value.trim() : "") });
  const dPayload = Object.assign({}, dest, { name: destName || (destInput ? destInput.value.trim() : "") });
  const result = await getJson("/api/route", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ origin: oPayload, dest: dPayload, rain_mm: rainMm(), prefer, use_zones: useZones }),
  });
  if (result.error) {
    layers.route.clearLayers();
    routeBox.innerHTML = `<span class="bad">${result.error}</span>`;
    return;
  }
  routeResult = result;
  selectedRouteId = result.recommended_id
    || (result.options && result.options[0] && result.options[0].id)
    || null;
  drawRouteOptions(result, selectedRouteId);
  renderRouteBox(result);
  lastRouteSignature = routeSignature(result);
  drawPathZones();
  renderWeatherPanel(scenarioData || {});
}

function stopZonePoll() {
  if (zonePoll) {
    clearInterval(zonePoll);
    zonePoll = null;
  }
  lastZoneFingerprint = null;
  if (rerouteNote) {
    rerouteNote.hidden = true;
    rerouteNote.textContent = "";
  }
}

function startZonePoll() {
  if (zonePoll) clearInterval(zonePoll);
  zonePoll = setInterval(pollLiveWeather, 45000);
}

function routeSignature(result) {
  if (!result || !result.options) return "";
  const rec = result.options.find((o) => o.id === result.recommended_id) || result.options[0];
  if (!rec) return "";
  return `${rec.id}:${rec.km}:${rec.minutes}:${(rec.via || []).join(",")}`;
}

async function pollLiveWeather() {
  if (!useZones) return;
  const pack = await getJson("/api/rainfall/zones");
  const next = zoneFingerprint(pack.zones);
  const delta = maxRainDelta(lastZoneFingerprint, pack.zones);
  const prevSig = lastRouteSignature;
  lastZoneFingerprint = next;
  await loadScenario();
  if (origin && dest && delta >= REROUTE_MM) {
    await computeRoute();
    const nowSig = routeSignature(routeResult);
    if (rerouteNote) {
      rerouteNote.hidden = false;
      rerouteNote.textContent = nowSig && prevSig && nowSig !== prevSig
        ? `Live rain changed by ${delta.toFixed(0)} mm in at least one cell. Ambulance path was updated.`
        : `Live rain changed by ${delta.toFixed(0)} mm. Current path is still acceptable.`;
    }
  }
}

async function enableSimulation() {
  markRainMode(false);
  stopZonePoll();
  liveRainNote.textContent = "Manual / Simulation: one rainfall value for all of NCR. Slider and presets are active.";
  await loadScenario();
  layers.route.clearLayers();
}

async function enableLiveWeather() {
  markRainMode(true);
  const pack = await getJson("/api/rainfall/zones");
  const bits = (pack.zones || [])
    .slice(0, 4)
    .map((z) => `${z.name} ${z.rain_mm == null ? "?" : z.rain_mm + " mm"}`)
    .join("; ");
  if (pack.stale) {
    liveRainNote.textContent = `Real-Time Weather Monitoring (stale). ${bits}. Missing rain is not treated as 0 mm.`;
  } else if (!pack.ok) {
    liveRainNote.textContent = `Real-Time Weather Monitoring unavailable (${pack.source}). Routing treats missing cells as uncertain, not dry.`;
  } else {
    liveRainNote.textContent = `Real-Time Weather Monitoring on (${pack.source}). ${bits}. Move the slider to return to simulation.`;
  }
  lastZoneFingerprint = zoneFingerprint(pack.zones);
  await loadScenario();
  startZonePoll();
  if (origin && dest) await computeRoute();
}

let rainTimer = null;
rainEl.addEventListener("input", () => {
  rainValue.textContent = String(rainMm());
  markRainMode(false);
  stopZonePoll();
  clearTimeout(rainTimer);
  rainTimer = setTimeout(async () => {
    await loadScenario();
    layers.route.clearLayers();
  }, 120);
});

document.querySelectorAll("[data-rain]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    rainEl.value = btn.dataset.rain;
    await enableSimulation();
  });
});

if (simModeBtn) simModeBtn.addEventListener("click", enableSimulation);
if (liveModeBtn) liveModeBtn.addEventListener("click", enableLiveWeather);

document.getElementById("routeBtn").addEventListener("click", computeRoute);
presetEl.addEventListener("change", applyPreset);

document.querySelectorAll("[data-prefer]").forEach((btn) => {
  btn.addEventListener("click", () => {
    prefer = btn.dataset.prefer;
    document.querySelectorAll("[data-prefer]").forEach((b) => b.classList.toggle("is-active", b === btn));
    if (origin && dest) computeRoute();
  });
});

map.on("click", async (ev) => {
  const pt = { lat: ev.latlng.lat, lon: ev.latlng.lng };
  const kind = clickMode === "origin" ? "origin" : "dest";
  clickMode = kind === "origin" ? "dest" : "origin";
  const rev = await getJson(`/api/reverse?lat=${pt.lat}&lon=${pt.lon}`);
  const name = rev.name || `${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)}`;
  setPoint(kind, pt, name);
  if (locationStatus) locationStatus.textContent = kind === "origin" ? "Origin set from map." : "Destination set from map.";
});

async function applyTypedPlace(kind) {
  const input = kind === "origin" ? originInput : destInput;
  if (!input) return;
  const q = input.value.trim();
  if (!q) return;
  const hit = landmarkByName(q);
  if (hit) {
    setPoint(kind, { lat: hit.lat, lon: hit.lon, node: hit.id }, q || hit.name);
    return;
  }
  if (q.length < 2) return;
  const pack = await getJson(`/api/geocode?q=${encodeURIComponent(q)}`);
  const first = (pack.results || [])[0];
  if (!first) {
    if (locationStatus) locationStatus.textContent = "No match. Try a landmark or click the map.";
    return;
  }
  fillPlaceList((pack.results || []).map((r) => r.label || r.name));
  setPoint(kind, { lat: first.lat, lon: first.lon }, q || first.name);
}

let searchTimer = null;
function onPlaceInput(kind) {
  const input = kind === "origin" ? originInput : destInput;
  const q = (input && input.value) || "";
  if (kind === "origin") {
    if (q.trim()) originName = q.trim();
  } else {
    if (q.trim()) destName = q.trim();
  }
  syncPresetDropdown();
  drawPicks();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    if (q.length < 2) return;
    const pack = await getJson(`/api/geocode?q=${encodeURIComponent(q)}`);
    fillPlaceList((pack.results || []).map((r) => r.label || r.name));
  }, 280);
}

if (originInput) {
  originInput.addEventListener("input", () => onPlaceInput("origin"));
  originInput.addEventListener("change", () => applyTypedPlace("origin"));
}
if (destInput) {
  destInput.addEventListener("input", () => onPlaceInput("dest"));
  destInput.addEventListener("change", () => applyTypedPlace("dest"));
}

if (themeToggle) {
  applyTheme(document.documentElement.dataset.theme || "dark");
  themeToggle.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  });
}

if (liveLocation) {
  liveLocation.addEventListener("click", async () => {
    if (!navigator.geolocation) {
      if (locationStatus) locationStatus.textContent = "This browser has no GPS.";
      return;
    }
    if (locationStatus) locationStatus.textContent = "Asking for location…";
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const kmh = pos.coords.speed == null ? null : pos.coords.speed * 3.6;
        if (window.JalMarg && typeof JalMarg.reportFix === "function" && kmh != null) {
          JalMarg.reportFix({ lat, lon, speed_kmh: kmh });
        }
        const rev = await getJson(`/api/reverse?lat=${lat}&lon=${lon}`);
        setPoint("origin", { lat, lon }, rev.name || "My location");
        map.setView([lat, lon], Math.max(map.getZoom(), 13));
        if (locationStatus) locationStatus.textContent = "From set to live GPS.";
      },
      (err) => {
        if (locationStatus) locationStatus.textContent = err.code === 1
          ? "Location blocked. Allow it in the address bar."
          : "Could not get GPS.";
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
    );
  });
}

(async function init() {
  meta = await getJson("/api/meta");
  map.setView([meta.city.lat, meta.city.lon], meta.city.zoom);
  fillPlaceList();
  for (const p of meta.presets) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.label;
    presetEl.appendChild(opt);
  }
  applyPreset();
  await loadScenario();
})();
