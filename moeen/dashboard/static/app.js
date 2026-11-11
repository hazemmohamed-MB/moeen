/* Moeen dashboard - polls the local API; never touches the webcam. */
"use strict";

(() => {
  const cfg = document.body.dataset;
  const STATUS_MS = Number(cfg.statusPollMs) || 1000;
  const EVENTS_MS = Number(cfg.eventsPollMs) || 3000;
  const PREVIEW = cfg.previewEnabled === "true";
  const OPEN = new Set(["MONITORING", "NEW"]);
  const LIVE_STATES = new Set(["RECOVERY_WINDOW", "MONITORING", "ALERT"]);

  const $ = (id) => document.getElementById(id);
  const el = {
    link: $("link"), band: $("band"), title: $("band-title"), detail: $("band-detail"),
    actions: $("band-actions"), assist: $("act-assist"), resolve: $("act-resolve"),
    meter: $("meter"), score: $("score-value"), parts: $("parts"),
    state: $("f-state"), condition: $("f-condition"), severity: $("f-severity"),
    duration: $("f-duration"), next: $("f-next"), eventTime: $("f-event-time"), person: $("f-person"),
    sound: $("f-sound"),
    preview: $("preview"), previewEmpty: $("preview-empty"),
    events: $("events"), eventsEmpty: $("events-empty"), count: $("history-count"),
    openOnly: $("open-only"), toast: $("toast"),
  };

  // ------------------------------------------------------------ wording
  const STATE_NAMES = {
    NORMAL: "Normal", POSSIBLE_FALL: "Checking a possible fall", RECOVERY_WINDOW: "Waiting for recovery",
    MONITORING: "Monitoring", ALERT: "Alert", RESOLVED: "Resolved",
  };
  const CONDITION_NAMES = { FALL: "Fall", LYING: "Lying or low posture", IMMOBILITY: "No movement" };
  const STATUS_NAMES = {
    MONITORING: "Monitoring", NEW: "Needs attention", ASSISTANCE_RECORDED: "Assistance recorded",
    RESOLVED: "Resolved",
  };
  const PART_NAMES = {
    velocity: "Fast drop", angle: "Body tilt", posture: "Low posture", stillness: "Stillness",
    persistence: "Time elapsed",
  };

  function headline(s) {
    const cond = s.condition;
    switch (s.state) {
      case "NORMAL": return ["All clear", s.person_visible ? "Nothing unusual right now." : "No person in view right now."];
      case "POSSIBLE_FALL": return ["Checking a possible fall", "Fast downward movement seen. Confirming in a moment."];
      case "RECOVERY_WINDOW": return ["Possible fall", "Waiting to see whether the person gets up."];
      case "MONITORING":
        return cond === "IMMOBILITY"
          ? ["Watching: no movement", "The person has been still for a while. This alone is not an alert."]
          : ["Watching: person is down", "The person is lying or low. Moeen alerts if this continues without movement."];
      case "ALERT": {
        const what = { FALL: "Fall without recovery", IMMOBILITY: "Down and not moving",
                       LYING: "Lying for a long time" }[cond] || "Unusual situation";
        return ["Needs attention", `${what}. Please check on the person.`];
      }
      case "RESOLVED": {
        const how = {
          ASSISTANCE_RECORDED: "Assistance was recorded.",
          RECOVERED: "The person got up on their own.",
          RECOVERED_AFTER_ALERT: "The person got up after the alert.",
        }[s.incident && s.incident.resolution] || "The incident is closed.";
        return ["Resolved", `${how} Normal monitoring resumes shortly.`];
      }
      default: return ["Unknown state", s.state];
    }
  }

  const TONES = { NORMAL: "calm", POSSIBLE_FALL: "watch", RECOVERY_WINDOW: "watch",
                  MONITORING: "watch", ALERT: "alert", RESOLVED: "done" };

  // ------------------------------------------------------------ formatting
  function fmtDuration(sec) {
    if (sec == null) return "Not applicable";
    const s = Math.max(0, Math.round(sec));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
    if (m) return `${m} min ${String(r).padStart(2, "0")} s`;
    return `${r} s`;
  }
  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const today = new Date();
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    if (d.toDateString() === today.toDateString()) return time;
    return `${d.toLocaleDateString([], { day: "numeric", month: "short" })}, ${time}`;
  }
  function nextStep(t) {
    if (!t) return "Nothing pending";
    const s = (v) => `${Math.max(0, Math.ceil(v))} s`;
    if (t.confirm_remaining_s != null) return `Confirming within ${s(t.confirm_remaining_s)}`;
    if (t.extension_remaining_s != null) return `Alert in ${s(t.extension_remaining_s)} unless the person gets up`;
    if (t.recovery_remaining_s != null) return `Alert in ${s(t.recovery_remaining_s)} unless the person gets up`;
    if (t.escalation_in_s != null) return `Alert in ${s(t.escalation_in_s)} if this continues`;
    if (t.alert_elapsed_s != null) return `Alert raised ${fmtDuration(t.alert_elapsed_s)} ago`;
    if (t.resolved_remaining_s != null) return `Back to normal in ${s(t.resolved_remaining_s)}`;
    return "Nothing pending";
  }

  // ------------------------------------------------------------ network
  async function api(path, options = {}) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    try {
      const res = await fetch(path, { ...options, signal: ctrl.signal, cache: "no-store" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
      return body;
    } finally {
      clearTimeout(timer);
    }
  }
  function setLink(ok, text) {
    el.link.dataset.ok = String(ok);
    el.link.textContent = text;
  }

  // ------------------------------------------------------------ status
  let lastTone = null;
  let currentEvent = null;  // {id, status} of the live incident's event
  let liveIncident = null;  // {eventId, duration_s} so the history row shows the live duration

  function renderMeter(score, tone) {
    const on = Math.round(Math.max(0, Math.min(1, score)) * 10);
    el.meter.style.setProperty("--meter-tone", `var(--${tone === "calm" ? "calm" : tone})`);
    [...el.meter.children].forEach((seg, i) => seg.classList.toggle("on", i < on));
    el.meter.setAttribute("aria-valuenow", score.toFixed(2));
    el.score.textContent = score.toFixed(2);
  }

  function renderParts(parts) {
    el.parts.replaceChildren(...Object.entries(parts || {}).map(([k, v]) => {
      const li = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = PART_NAMES[k] || k;
      const bar = document.createElement("span");
      bar.className = "bar";
      const fill = document.createElement("i");
      fill.style.width = `${Math.round(v * 100)}%`;
      bar.append(fill);
      const val = document.createElement("span");
      val.className = "num";
      val.textContent = v.toFixed(2);
      li.append(name, bar, val);
      return li;
    }));
  }

  function setBand(tone, title, detail) {
    el.band.dataset.tone = tone;
    el.title.textContent = title;
    el.detail.textContent = detail;
    if (tone === "alert" && lastTone !== "alert") {
      el.band.classList.remove("is-new-alert");
      void el.band.offsetWidth;            // restart the one-time pulse
      el.band.classList.add("is-new-alert");
    }
    lastTone = tone;
    document.title = tone === "alert" ? "Needs attention - Moeen" : "Moeen";
  }

  function renderStatus(d) {
    const s = d.snapshot;
    if (!d.pipeline_running) {
      setBand("idle", "Camera processing is not running",
               "Start Moeen with python -m moeen.app. Event history below still works.");
    } else if (!s || d.stale) {
      setBand("idle", "No recent update", `The camera loop has not reported for ${d.age_s ?? "?"} s.`);
    }
    if (s) {
      const tone = TONES[s.state] || "idle";
      if (d.pipeline_running && !d.stale) {
        const [t, detail] = headline(s);
        setBand(tone, t, detail);
      }
      renderMeter(s.score, tone);
      renderParts(s.score_components);
      el.state.textContent = STATE_NAMES[s.state] || s.state;
      el.condition.textContent = s.condition ? CONDITION_NAMES[s.condition] || s.condition : "None";
      const sev = s.risk_level === "NONE" ? "NONE" : s.risk_level;
      el.severity.dataset.level = sev;
      el.severity.textContent = sev === "NONE" ? "None" : sev[0] + sev.slice(1).toLowerCase();
      el.duration.textContent = s.incident && s.incident.open ? fmtDuration(s.incident.duration_s) : "Not applicable";
      el.next.textContent = nextStep(s.timers);
      el.person.textContent = s.person_visible
        ? `In view${s.posture && s.posture !== "UNKNOWN" ? `, ${s.posture.toLowerCase()}` : ""}`
        : "Not in view";
      el.sound.textContent = soundText(s.sound);
    }
    // event time: the live incident's start, otherwise the most recent stored event
    if (s && s.incident && s.incident.open) {
      el.eventTime.textContent = `Started ${fmtTime(s.incident.started_at)}`;
    } else if (d.last_event) {
      el.eventTime.textContent = `Last event ${fmtTime(d.last_event.created_at)}`;
    } else {
      el.eventTime.textContent = "No events yet";
    }
    // actions for the live incident's stored event
    currentEvent = s && s.event && OPEN.has(s.event.status) && LIVE_STATES.has(s.state) && d.pipeline_running
      ? s.event : null;
    liveIncident = currentEvent && s.incident ? { eventId: currentEvent.id, duration_s: s.incident.duration_s } : null;
    el.actions.hidden = !currentEvent;
    updatePreview(d.pipeline_running);
  }

  // the chime plays on the computer running Moeen, not in the browser
  function soundText(snd) {
    if (!snd) return "Unknown";
    if (!snd.enabled) return "Off";
    if (!snd.available) return "No audio output on this computer";
    if (snd.muted) return "Muted (press m in the camera window)";
    const sev = (snd.min_severity || "HIGH").toLowerCase();
    const played = snd.plays ? `, played ${snd.plays} time${snd.plays === 1 ? "" : "s"}` : "";
    return `On for ${sev}-severity alerts${played}`;
  }

  async function pollStatus() {
    try {
      renderStatus(await api("/api/status"));
      setLink(true, "Connected");
    } catch (err) {
      setLink(false, "Cannot reach Moeen, retrying");
      setBand("idle", "Dashboard is offline", "The Moeen program is not answering. It may have been closed.");
      el.actions.hidden = true;
    } finally {
      setTimeout(pollStatus, STATUS_MS);
    }
  }

  // ------------------------------------------------------------ preview
  let previewOn = false;
  function updatePreview(running) {
    if (!PREVIEW) {
      el.previewEmpty.textContent = "The camera preview is turned off in the settings.";
      return;
    }
    if (running && !previewOn) {
      previewOn = true;
      el.preview.src = `/video_feed?ts=${Date.now()}`;
    } else if (!running && previewOn) {
      previewOn = false;
      el.preview.removeAttribute("src");
      el.preview.hidden = true;
      el.previewEmpty.hidden = false;
      el.previewEmpty.textContent = "No camera picture: processing is not running.";
    }
  }
  el.preview.addEventListener("load", () => { el.preview.hidden = false; el.previewEmpty.hidden = true; });
  el.preview.addEventListener("error", () => {
    el.preview.hidden = true;
    el.previewEmpty.hidden = false;
    el.previewEmpty.textContent = "Camera picture unavailable. Retrying.";
    previewOn = false;                   // the next status poll reconnects
  });

  // ------------------------------------------------------------ actions
  function toast(text, kind = "info") {
    el.toast.textContent = text;
    el.toast.dataset.kind = kind;
    el.toast.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { el.toast.hidden = true; }, 4000);
  }

  async function act(eventId, kind, button) {
    if (button) button.disabled = true;
    try {
      const r = await api(`/api/events/${eventId}/${kind}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      toast(kind === "assistance" ? `Assistance recorded for event ${r.event.id}.` : `Event ${r.event.id} resolved.`);
      refreshEvents();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  // Resolve closes an event, so it asks for a second click within 3 seconds.
  function confirmThen(button, label, run) {
    if (button.classList.contains("is-confirming")) {
      button.classList.remove("is-confirming");
      button.textContent = label;
      run();
      return;
    }
    button.classList.add("is-confirming");
    button.textContent = "Click again to resolve";
    setTimeout(() => {
      button.classList.remove("is-confirming");
      button.textContent = label;
    }, 3000);
  }

  el.assist.addEventListener("click", () => { if (currentEvent) act(currentEvent.id, "assistance", el.assist); });
  el.resolve.addEventListener("click", () => {
    if (currentEvent) confirmThen(el.resolve, "Resolve", () => act(currentEvent.id, "resolve", el.resolve));
  });

  // ------------------------------------------------------------ event history
  const expanded = new Set();

  function cell(text, cls) {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    if (text instanceof Node) td.append(text); else td.textContent = text;
    return td;
  }

  function rowFor(e) {
    const tr = document.createElement("tr");
    tr.className = "event-row" + (e.status === "NEW" ? " is-open-event" : "");
    tr.tabIndex = 0;
    tr.dataset.id = e.id;
    tr.setAttribute("aria-expanded", String(expanded.has(e.id)));
    const sev = document.createElement("span");
    sev.className = "sev";
    sev.dataset.level = e.severity;
    sev.textContent = e.severity[0] + e.severity.slice(1).toLowerCase();
    const st = document.createElement("span");
    st.className = "status-pill";
    st.dataset.status = e.status;
    st.textContent = STATUS_NAMES[e.status] || e.status;
    const actions = document.createElement("div");
    actions.className = "row-actions";
    if (OPEN.has(e.status)) {
      const a = document.createElement("button");
      a.type = "button"; a.className = "row-btn"; a.textContent = "Assistance recorded";
      a.addEventListener("click", (ev) => { ev.stopPropagation(); act(e.id, "assistance", a); });
      actions.append(a);
    }
    if (e.status !== "RESOLVED") {
      const r = document.createElement("button");
      r.type = "button"; r.className = "row-btn"; r.textContent = "Resolve";
      r.addEventListener("click", (ev) => { ev.stopPropagation(); confirmThen(r, "Resolve", () => act(e.id, "resolve", r)); });
      actions.append(r);
    }
    tr.append(
      cell(fmtTime(e.created_at)), cell(CONDITION_NAMES[e.event_type] || e.event_type), cell(sev),
      cell(e.score.toFixed(2), "num"), cell(durationText(e), "num"),
      cell(st), cell(actions),
    );
    const toggle = () => {
      if (expanded.has(e.id)) expanded.delete(e.id); else expanded.add(e.id);
      refreshEvents();
    };
    tr.addEventListener("click", toggle);
    tr.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggle(); } });
    return tr;
  }

  function durationText(e) {
    if (liveIncident && liveIncident.eventId === e.id) return `${fmtDuration(liveIncident.duration_s)}, ongoing`;
    if (OPEN.has(e.status)) return "Ongoing";
    return e.duration_seconds == null ? "" : fmtDuration(e.duration_seconds);
  }

  async function detailRow(e) {
    const tr = document.createElement("tr");
    tr.className = "detail-row";
    const td = document.createElement("td");
    td.colSpan = 7;
    try {
      const d = await api(`/api/events/${e.id}`);
      const ul = document.createElement("ul");
      ul.className = "history-list";
      for (const h of d.history) {
        const li = document.createElement("li");
        const from = h.from_status ? STATUS_NAMES[h.from_status] || h.from_status : "Created";
        li.textContent = `${fmtTime(h.changed_at)}: ${from} to ${STATUS_NAMES[h.to_status] || h.to_status}`
          + (h.note ? `. ${h.note}` : "");
        ul.append(li);
      }
      const res = document.createElement("p");
      res.className = "muted";
      res.textContent = `Event ${e.id}${e.resolution ? `, ended as ${e.resolution.toLowerCase().replaceAll("_", " ")}` : ""}.`;
      td.append(res, ul);
    } catch (err) {
      td.textContent = err.message;
    }
    tr.append(td);
    return tr;
  }

  let eventsTimer = null;
  async function refreshEvents() {
    clearTimeout(eventsTimer);
    try {
      const q = el.openOnly.checked ? "&open=1" : "";
      const d = await api(`/api/events?limit=15${q}`);
      const rows = [];
      for (const e of d.events) {
        rows.push(rowFor(e));
        if (expanded.has(e.id)) rows.push(await detailRow(e));
      }
      el.events.replaceChildren(...rows);
      el.eventsEmpty.hidden = d.events.length > 0;
      el.eventsEmpty.textContent = el.openOnly.checked
        ? "No open events."
        : "No events yet. Falls, long lying and long stillness will appear here.";
      el.count.textContent = `${d.total} ${d.total === 1 ? "event" : "events"}, ${d.open} open`;
    } catch (err) {
      el.count.textContent = err.message;
    } finally {
      eventsTimer = setTimeout(refreshEvents, EVENTS_MS);
    }
  }
  el.openOnly.addEventListener("change", refreshEvents);

  pollStatus();
  refreshEvents();
})();
