/**
 * Feature 1 overlay + GPS ingest.
 *
 * LIVE mode: only real anonymized pings (JalMarg.reportFix).
 * SIMULATION mode: labelled test vehicles from /api/traffic/sim/*.
 *
 * Does not set origin/destination and does not request GPS permission.
 */
(function () {
  const LEVEL_COLOR = {
    clear: "#3dd68c",
    moderate: "#e6b325",
    heavy: "#ff5a3c",
  };

  const state = {
    layer: null,
    vehicleLayer: null,
    timer: null,
    lastHash: "",
    mode: "live",
  };

  function getMap() {
    return window.JalMarg && window.JalMarg.map;
  }

  function ensureLayers() {
    const map = getMap();
    if (!map || typeof L === "undefined") return null;
    if (!map.getPane("traffic")) {
      map.createPane("traffic");
      map.getPane("traffic").style.zIndex = 350;
    }
    if (!map.getPane("simVehicles")) {
      map.createPane("simVehicles");
      map.getPane("simVehicles").style.zIndex = 450;
    }
    if (!state.layer) {
      state.layer = L.layerGroup().addTo(map);
    }
    if (!state.vehicleLayer) {
      state.vehicleLayer = L.layerGroup().addTo(map);
    }
    injectLegend();
    injectStyles();
    injectPanel();
    return state.layer;
  }

  function injectStyles() {
    if (document.getElementById("traffic-style")) return;
    const s = document.createElement("style");
    s.id = "traffic-style";
    s.textContent = [
      ".swatch.traffic-clear{background:#3dd68c}",
      ".swatch.traffic-moderate{background:#e6b325}",
      ".swatch.traffic-heavy{background:#ff5a3c}",
      ".traffic-panel{position:absolute;right:12px;top:12px;z-index:2500;width:260px;background:#161b22;color:#c9d1d9;border:1px solid #30363d;padding:10px;font:12px/1.4 'IBM Plex Sans',sans-serif;pointer-events:auto}",
      ".traffic-panel h3{margin:0 0 6px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#e6b325}",
      ".traffic-panel .row{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}",
      ".traffic-panel button{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:4px 7px;cursor:pointer;font-size:11px}",
      ".traffic-panel button.on{border-color:#3dd68c;color:#3dd68c}",
      ".traffic-panel .meta{color:#8b949e;font-size:11px}",
      ".traffic-banner{position:absolute;left:12px;top:12px;z-index:500;background:#e6b325;color:#12171e;padding:6px 10px;font:11px/1.3 'IBM Plex Sans',sans-serif;font-weight:600;display:none}",
      ".traffic-banner.is-on{display:block}",
      ".traffic-dot{width:8px;height:8px;border-radius:50%;border:1px solid #0d1117}",
    ].join("");
    document.head.appendChild(s);
  }

  function injectLegend() {
    const legend = document.querySelector(".legend");
    if (!legend || legend.querySelector(".traffic-legend")) return;
    [
      ["traffic-clear", "Traffic clear"],
      ["traffic-moderate", "Moderate traffic"],
      ["traffic-heavy", "Heavy traffic"],
    ].forEach(([cls, label]) => {
      const span = document.createElement("span");
      span.className = "traffic-legend";
      span.innerHTML = `<i class="swatch ${cls}" aria-hidden="true"></i> ${label}`;
      legend.appendChild(span);
    });
  }

  function bindTrafficButtons(root) {
    const scope = root || document;
    const liveBtn = document.getElementById("trafficLiveBtn");
    const simBtn = document.getElementById("trafficSimBtn");
    if (liveBtn && !liveBtn.dataset.boundTraffic) {
      liveBtn.dataset.boundTraffic = "1";
      liveBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        setMode("live");
      });
    }
    if (simBtn && !simBtn.dataset.boundTraffic) {
      simBtn.dataset.boundTraffic = "1";
      simBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        setMode("simulation");
      });
    }
    scope.querySelectorAll("[data-scenario]").forEach((btn) => {
      if (btn.dataset.boundTraffic) return;
      btn.dataset.boundTraffic = "1";
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        startSim(btn.getAttribute("data-scenario"));
      });
    });
  }

  function injectPanel() {
    if (document.getElementById("traffic-panel")) {
      bindTrafficButtons(document.getElementById("traffic-panel"));
      return;
    }
    const host = document.getElementById("mapPanel") || document.body;
    host.style.position = "relative";
    const panel = document.createElement("div");
    panel.id = "traffic-panel";
    panel.className = "traffic-panel";
    panel.innerHTML = [
      "<h3>Feature 1 · traffic (dev)</h3>",
      '<div class="row">',
      '<button type="button" id="trafficLiveBtn" data-mode="live">LIVE MODE</button>',
      '<button type="button" id="trafficSimBtn" data-mode="simulation">SIMULATION MODE</button>',
      "</div>",
      '<div class="row" id="traffic-scenarios">',
      '<button type="button" data-scenario="clear">Clear</button>',
      '<button type="button" data-scenario="moderate">Moderate</button>',
      '<button type="button" data-scenario="heavy">Heavy</button>',
      '<button type="button" data-scenario="mixed">Mixed</button>',
      "</div>",
      '<div class="meta" id="traffic-meta">LIVE MODE — real GPS pings only. Simulation is a test harness.</div>',
    ].join("");
    host.appendChild(panel);
    if (window.L && L.DomEvent) {
      L.DomEvent.disableClickPropagation(panel);
      L.DomEvent.disableScrollPropagation(panel);
    }
    bindTrafficButtons(panel);
  }

  function setBanner(on, text) {
    let el = document.getElementById("traffic-banner");
    if (!el) {
      const host = document.getElementById("mapPanel") || document.body;
      el = document.createElement("div");
      el.id = "traffic-banner";
      el.className = "traffic-banner";
      host.appendChild(el);
    }
    el.textContent = text || "DEV SIMULATION — test vehicles, not live users";
    el.classList.toggle("is-on", !!on);
  }

  function setPanel(mode, extra) {
    state.mode = mode;
    document.querySelectorAll("[data-mode]").forEach((b) => {
      const on = b.getAttribute("data-mode") === mode;
      b.classList.toggle("on", on);
      b.classList.toggle("is-active", on);
    });
    const meta = document.getElementById("traffic-meta");
    if (meta) meta.textContent = extra || (mode === "simulation" ? "SIMULATION" : "LIVE — real GPS only");
  }

  function drawEdges(data) {
    const layer = ensureLayers();
    if (!layer) return;
    const edges = (data && data.edges) || [];
    const hash =
      (data.mode || "") +
      edges
        .map((e) => {
          const n = e.n || e.n || 0;
          const med = e.median_kmh || e.median_kmh || 0;
          return `${e.a}-${e.b}:${med}:${n}`;
        })
        .join("|");
    if (hash === state.lastHash) return;
    state.lastHash = hash;
    layer.clearLayers();
    edges.forEach((e) => {
      const coords = e.coords || e.coords;
      if (!coords || coords.length < 2) return;
      const n = e.n || e.n || 0;
      const med = e.median_kmh || e.median_kmh;
      const mean = e.mean_kmh || e.mean_kmh;
      L.polyline(coords, {
        pane: "traffic",
        color: LEVEL_COLOR[e.level] || "#888",
        weight: e.level === "heavy" ? 5 : 3,
        opacity: 0.75,
        interactive: true,
      })
        .bindPopup(
          `<b>${e.name}</b><br>${n} vehicle${n === 1 ? "" : "s"} · median ${med} km/h (mean ${mean})<br>${e.level}`
        )
        .addTo(layer);
    });
  }

  function drawVehicles(vehicles) {
    if (!state.vehicleLayer) return;
    state.vehicleLayer.clearLayers();
    if (state.mode !== "simulation") return;
    (vehicles || []).forEach((v) => {
      const color = v.speed_kmh < 1 ? "#ff5a3c" : v.speed_kmh < 14 ? "#e6b325" : "#3dd68c";
      L.circleMarker([v.lat, v.lon], {
        pane: "simVehicles",
        radius: 5,
        color: "#0d1117",
        weight: 1,
        fillColor: color,
        fillOpacity: 0.95,
      })
        .bindPopup(
          `<b>${v.id}</b> (simulated)<br>${v.speed_kmh} km/h · heading ${v.heading || "—"}°<br>${v.name || "off network"}`
        )
        .addTo(state.vehicleLayer);
    });
  }

  async function refresh() {
    try {
      const res = await fetch("/api/traffic");
      if (!res.ok) return;
      const data = await res.json();
      state.mode = data.mode || "live";
      const n = data.sample_count || data.sample_count || 0;
      const extra =
        data.mode === "simulation"
          ? `SIMULATION · ${data.vehicle_count || 0} test vehicles · ${data.edge_count} roads`
          : `LIVE · ${n} anonymized samples`;
      setPanel(state.mode, extra);
      setBanner(state.mode === "simulation", extra);
      drawEdges(data);
      if (state.mode === "simulation") {
        const vr = await fetch("/api/traffic/sim/vehicles");
        if (vr.ok) {
          const body = await vr.json();
          drawVehicles(body.vehicles);
        }
      } else if (state.vehicleLayer) {
        state.vehicleLayer.clearLayers();
      }
    } catch (_) {
      /* overlay is best-effort */
    }
  }

  async function setMode(mode) {
    setPanel(mode, mode === "simulation" ? "Starting simulation…" : "Switching to live GPS…");
    try {
      const res = await fetch("/api/traffic/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!res.ok) {
        setPanel("live", `Could not set mode (${res.status}). Restart the server, then Ctrl+F5.`);
        return;
      }
    } catch (err) {
      setPanel("live", "Traffic API unreachable. Restart the JalMarg server.");
      return;
    }
    state.lastHash = "";
    if (mode === "simulation") {
      await startSim("moderate");
      return;
    }
    refresh();
  }

  async function startSim(scenario) {
    setPanel("simulation", `Starting ${scenario} simulation…`);
    document.querySelectorAll("[data-scenario]").forEach((b) => {
      const on = b.getAttribute("data-scenario") === scenario;
      b.classList.toggle("on", on);
      b.classList.toggle("is-active", on);
    });
    try {
      const res = await fetch(
        "/api/traffic/sim/start?scenario=" + encodeURIComponent(scenario),
        { method: "POST" }
      );
      if (!res.ok) {
        const text = await res.text();
        setPanel("simulation", `Simulation failed (${res.status}). ${text.slice(0, 120)}`);
        return;
      }
    } catch (err) {
      setPanel("simulation", "Simulation API unreachable. Restart the JalMarg server.");
      return;
    }
    state.lastHash = "";
    refresh();
  }

  let pingQueue = [];
  let pingTimer = null;

  function reportFix(fix) {
    if (!fix || fix.lat == null || fix.lon == null) return;
    const speed = fix.speedKmh != null ? fix.speedKmh : fix.speed_kmh;
    if (speed == null) return;
    pingQueue.push({ lat: fix.lat, lon: fix.lon, speed_kmh: speed });
    if (pingTimer) return;
    pingTimer = setTimeout(flushPings, 4000);
  }

  async function flushPings() {
    pingTimer = null;
    if (!pingQueue.length) return;
    const batch = pingQueue.splice(0, 40);
    try {
      await fetch("/api/traffic/ping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fixes: batch }),
      });
    } catch (_) {
      /* drop batch */
    }
  }

  function start() {
    if (state.timer) return;
    injectPanel();
    ensureLayers();
    refresh();
    state.timer = setInterval(refresh, 2000);
  }

  window.JalMarg = Object.assign(window.JalMarg || {}, {
    reportFix,
    startTraffic: start,
    setMode,
    startSim,
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
