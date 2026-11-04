/* SnapDump analysis: independent FFDC workspace page. */
(() => {
"use strict";
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
if (!$("#snapdump-page")) return;

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  const requestId = response.headers.get("X-Request-ID") || "";
  const raw = await response.text();
  let data = {};
  try { data = raw ? JSON.parse(raw) : {}; }
  catch {
    const reference = requestId ? ` Request ID: ${requestId}.` : "";
    throw new Error(`The server returned HTTP ${response.status} with an invalid response.${reference}`);
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}


function showToast(message) {
  const toast = $("#snapdump-toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 3200);
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  const gib = bytes / 1024 ** 3;
  return `${gib >= 10 ? gib.toFixed(0) : gib.toFixed(1)} GiB`;
}


function cleanAssistantText(content) {
  let text = String(content || "");
  text = text.replace(/<\s*(think|thinking)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, "");
  text = text.replace(/^[\s\S]*?<\s*\/\s*(?:think|thinking)\s*>/i, "");
  text = text.replace(/<\s*(?:think|thinking)\b[^>]*>[\s\S]*$/i, "");
  text = text.replace(/<\s*\/?\s*(?:think|thinking)\b[^>]*>/gi, "");
  return text.trim();
}

function appendInlineMarkdown(parent, text) {
  const pattern = /(\*\*[^*\n]+?\*\*|`[^`\n]+?`|\[[^\]\n]+?\]\((?:https?:\/\/|mailto:)[^)\s]+?\)|\*[^*\n]+?\*)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) parent.append(document.createTextNode(text.slice(cursor, match.index)));
    const token = match[0];
    if (token.startsWith("**")) {
      const strong = document.createElement("strong"); strong.textContent = token.slice(2, -2); parent.append(strong);
    } else if (token.startsWith("`")) {
      const code = document.createElement("code"); code.textContent = token.slice(1, -1); parent.append(code);
    } else if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        const link = document.createElement("a"); link.textContent = linkMatch[1]; link.href = linkMatch[2];
        link.target = "_blank"; link.rel = "noopener noreferrer"; parent.append(link);
      }
    } else {
      const emphasis = document.createElement("em"); emphasis.textContent = token.slice(1, -1); parent.append(emphasis);
    }
    cursor = match.index + token.length;
  }
  if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
}

function renderMarkdown(container, markdown) {
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  const tableDivider = (line) => /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
  const tableCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
  const isBlockStart = (line) => /^\s*$|^\s*```|^#{1,6}\s+|^\s*[-+*]\s+|^\s*\d+[.)]\s+|^\s*>\s?|^\s*(?:---+|\*\*\*+)\s*$/.test(line);
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) { index += 1; continue; }
    if (/^\s*```/.test(line)) {
      const language = line.trim().slice(3).trim(); const codeLines = []; index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) codeLines.push(lines[index++]);
      if (index < lines.length) index += 1;
      const pre = document.createElement("pre"); const code = document.createElement("code");
      if (language) code.dataset.language = language; code.textContent = codeLines.join("\n"); pre.append(code); container.append(pre); continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      const element = document.createElement(`h${heading[1].length}`); appendInlineMarkdown(element, heading[2]); container.append(element); index += 1; continue;
    }
    if (line.includes("|") && index + 1 < lines.length && tableDivider(lines[index + 1])) {
      const headers = tableCells(line); const alignments = tableCells(lines[index + 1]);
      const wrapper = document.createElement("div"); wrapper.className = "markdown-table-wrap";
      const table = document.createElement("table"); const head = document.createElement("thead"); const headRow = document.createElement("tr");
      headers.forEach((value, column) => {
        const cell = document.createElement("th"); appendInlineMarkdown(cell, value);
        const alignment = alignments[column] || "";
        if (/^:.*:$/.test(alignment)) cell.style.textAlign = "center";
        else if (/:$/.test(alignment)) cell.style.textAlign = "right";
        headRow.append(cell);
      });
      head.append(headRow); table.append(head); index += 2;
      const body = document.createElement("tbody");
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const row = document.createElement("tr"); const values = tableCells(lines[index]);
        headers.forEach((_, column) => {
          const cell = document.createElement("td"); appendInlineMarkdown(cell, values[column] || "");
          const alignment = alignments[column] || "";
          if (/^:.*:$/.test(alignment)) cell.style.textAlign = "center";
          else if (/:$/.test(alignment)) cell.style.textAlign = "right";
          row.append(cell);
        });
        body.append(row); index += 1;
      }
      table.append(body); wrapper.append(table); container.append(wrapper); continue;
    }
    const unordered = line.match(/^\s*[-+*]\s+(.+)$/);
    if (unordered) {
      const list = document.createElement("ul");
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-+*]\s+(.+)$/); if (!item) break;
        const listItem = document.createElement("li"); appendInlineMarkdown(listItem, item[1]); list.append(listItem); index += 1;
      }
      container.append(list); continue;
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      const list = document.createElement("ol");
      while (index < lines.length) {
        const item = lines[index].match(/^\s*\d+[.)]\s+(.+)$/); if (!item) break;
        const listItem = document.createElement("li"); appendInlineMarkdown(listItem, item[1]); list.append(listItem); index += 1;
      }
      container.append(list); continue;
    }
    if (/^\s*>/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^\s*>/.test(lines[index])) quoteLines.push(lines[index++].replace(/^\s*>\s?/, ""));
      const quote = document.createElement("blockquote"); appendInlineMarkdown(quote, quoteLines.join(" ")); container.append(quote); continue;
    }
    if (/^\s*(?:---+|\*\*\*+)\s*$/.test(line)) { container.append(document.createElement("hr")); index += 1; continue; }
    const paragraphLines = [line.trim()]; index += 1;
    while (index < lines.length && !isBlockStart(lines[index])) paragraphLines.push(lines[index++].trim());
    const paragraph = document.createElement("p"); appendInlineMarkdown(paragraph, paragraphLines.join(" ")); container.append(paragraph);
  }
}


const snapdumpState = { file: null, result: null, selectedFile: "", generation: 0, busy: false };
const snapdumpChatState = { history: [], generation: 0, busy: false, controller: null, failed: null };

function updateSnapdumpChatControls() {
  const unavailable = !snapdumpState.result?.analysis_id;
  const busy = snapdumpChatState.busy;
  $("#snapdump-chat-question").disabled = unavailable || busy;
  $("#snapdump-chat-send").disabled = unavailable || busy || !$("#snapdump-chat-question").value.trim();
  $("#snapdump-chat-send").textContent = busy ? "Thinking…" : "Send";
  $("#snapdump-chat-retry").disabled = unavailable || busy;
  $$("[data-snapdump-question]").forEach((button) => { button.disabled = unavailable || busy; });
  $("#snapdump-chat-messages").setAttribute("aria-busy", String(busy));
}

function resetSnapdumpChat() {
  snapdumpChatState.generation += 1;
  snapdumpChatState.controller?.abort();
  snapdumpChatState.controller = null;
  snapdumpChatState.history = [];
  snapdumpChatState.busy = false;
  snapdumpChatState.failed = null;
  $("#snapdump-chat-question").value = "";
  $("#snapdump-chat-error").classList.add("hidden");
  $("#snapdump-chat-error-message").textContent = "";
  $("#snapdump-chat-status").textContent = "";
  $("#snapdump-chat-context").textContent = snapdumpState.result?.filename || "Current SnapDump";
  const welcome = document.createElement("div");
  welcome.className = "snapdump-chat-welcome";
  const heading = document.createElement("strong"); heading.textContent = "What would you like to know?";
  const copy = document.createElement("p"); copy.textContent = "Ask a question below, or start with a suggested question. Each answer can be followed by another question.";
  welcome.append(heading, copy);
  $("#snapdump-chat-messages").replaceChildren(welcome);
  updateSnapdumpChatControls();
}

function appendSnapdumpChatMessage(role, content) {
  $(".snapdump-chat-welcome")?.remove();
  const message = document.createElement("article");
  message.className = `snapdump-chat-message ${role}`;
  const author = document.createElement("strong"); author.className = "snapdump-chat-author";
  author.textContent = role === "user" ? "You" : "Davy AI";
  const body = document.createElement("div"); body.className = "snapdump-chat-body";
  if (role === "assistant") renderMarkdown(body, cleanAssistantText(content));
  else body.textContent = content;
  message.append(author, body);
  $("#snapdump-chat-messages").append(message);
  $("#snapdump-chat-messages").scrollTop = $("#snapdump-chat-messages").scrollHeight;
  return message;
}

function appendSnapdumpChatSources(message, sources, result) {
  if (!Array.isArray(sources)) return;
  sources = sources.filter((source) => source && typeof source.name === "string");
  if (!sources.length) return;
  const wrapper = document.createElement("details"); wrapper.className = "snapdump-chat-sources";
  const heading = document.createElement("summary"); heading.textContent = `Supporting logs (${sources.length})`; wrapper.append(heading);
  sources.forEach((source) => {
    const details = document.createElement("details"); details.className = "snapdump-chat-source";
    const summary = document.createElement("summary");
    const sourceId = document.createElement("span"); sourceId.className = "snapdump-chat-source-id"; sourceId.textContent = source.id || "Source";
    const name = document.createElement("span"); name.className = "snapdump-chat-source-name"; name.textContent = source.name;
    const start = Number(source.start_line); const end = Number(source.end_line);
    const lines = document.createElement("small");
    lines.textContent = Number.isInteger(start) && start > 0 ? (Number.isInteger(end) && end >= start && end !== start ? `Lines ${start}–${end}` : `Line ${start}`) : "Log excerpt";
    summary.append(sourceId, name, lines);
    const excerpt = document.createElement("pre"); excerpt.textContent = String(source.excerpt || "No excerpt available.");
    const open = document.createElement("button"); open.type = "button"; open.className = "secondary"; open.textContent = "Open original log";
    open.disabled = !Object.hasOwn(result.file_urls || {}, source.name);
    open.addEventListener("click", () => {
      if (snapdumpState.result !== result) return;
      $("#snapdump-file-filter").value = "";
      loadSnapdumpFile(source.name, start, end);
      $("#snapdump-file-explorer").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    details.append(summary, excerpt, open); wrapper.append(details);
  });
  message.append(wrapper);
}

async function askSnapdumpQuestion(question, retry = false) {
  const result = snapdumpState.result;
  question = String(question || "").trim();
  if (!result?.analysis_id || !question || snapdumpChatState.busy) return;
  if (question.length > 4000) { showToast("Questions must be 4,000 characters or fewer."); return; }
  const failed = retry ? snapdumpChatState.failed : null;
  const userMessage = failed?.question === question ? failed.userMessage : appendSnapdumpChatMessage("user", question);
  userMessage.querySelector(".snapdump-chat-unanswered")?.remove();
  snapdumpChatState.failed = null;
  snapdumpChatState.busy = true;
  const generation = ++snapdumpChatState.generation;
  const controller = new AbortController(); snapdumpChatState.controller = controller;
  $("#snapdump-chat-question").value = "";
  $("#snapdump-chat-error").classList.add("hidden");
  $("#snapdump-chat-error-message").textContent = "";
  $("#snapdump-chat-status").textContent = "Davy is reading the logs and preparing an answer…";
  const loading = appendSnapdumpChatMessage("loading", "Reading the evidence in this SnapDump…");
  updateSnapdumpChatControls();
  const current = () => generation === snapdumpChatState.generation && snapdumpState.result === result;
  try {
    const data = await api("/api/snapdump/ask", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ analysis_id: result.analysis_id, question, history: snapdumpChatState.history.slice(-10).map(({ role, content }) => ({ role, content: content.slice(0, 8000) })) }),
    });
    if (!current()) return;
    if (data.analysis_id !== result.analysis_id || typeof data.answer !== "string" || !cleanAssistantText(data.answer)) throw new Error("The server did not return an answer for this SnapDump. Please retry.");
    loading.remove();
    const answer = cleanAssistantText(data.answer);
    const message = appendSnapdumpChatMessage("assistant", answer);
    appendSnapdumpChatSources(message, data.sources, result);
    snapdumpChatState.history.push({ role: "user", content: question }, { role: "assistant", content: answer });
    snapdumpChatState.history = snapdumpChatState.history.slice(-10);
    $("#snapdump-chat-status").textContent = "Answer ready. Ask a follow-up or open a supporting log.";
    $("#snapdump-chat-messages").scrollTop = Math.max(0, message.offsetTop - 12);
  } catch (error) {
    if (!current()) return;
    loading.remove();
    const unanswered = document.createElement("small"); unanswered.className = "snapdump-chat-unanswered"; unanswered.textContent = "Not answered"; userMessage.append(unanswered);
    snapdumpChatState.failed = { question, userMessage };
    $("#snapdump-chat-error-message").textContent = `Unable to answer: ${error.message}`;
    $("#snapdump-chat-error").classList.remove("hidden");
    $("#snapdump-chat-status").textContent = "You can retry this question or ask a different question.";
  } finally {
    if (current()) {
      snapdumpChatState.busy = false; snapdumpChatState.controller = null;
      updateSnapdumpChatControls();
      if (!$("#snapdump-page").classList.contains("hidden")) $("#snapdump-chat-question").focus({ preventScroll: true });
    }
  }
}

$("#snapdump-chat-form").addEventListener("submit", (event) => { event.preventDefault(); askSnapdumpQuestion($("#snapdump-chat-question").value); });
$("#snapdump-chat-question").addEventListener("input", updateSnapdumpChatControls);
$("#snapdump-chat-question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault(); askSnapdumpQuestion(event.currentTarget.value);
  }
});
$("#snapdump-chat-clear").addEventListener("click", () => { resetSnapdumpChat(); $("#snapdump-chat-question").focus({ preventScroll: true }); });
$("#snapdump-chat-retry").addEventListener("click", () => { if (snapdumpChatState.failed) askSnapdumpQuestion(snapdumpChatState.failed.question, true); });
$$("[data-snapdump-question]").forEach((button) => button.addEventListener("click", () => askSnapdumpQuestion(button.dataset.snapdumpQuestion)));

function snapdumpEscape(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[char]));
}

function snapdumpSeverityLabel(severity) {
  return { ok: "OK", warn: "Attention", critical: "Fault", info: "Info" }[severity] || "Unknown";
}

function snapdumpReported(value) {
  if (value === null || value === undefined || (typeof value === "string" && (!value.trim() || value.trim().toLowerCase() === "unknown"))) return "Not reported";
  return value;
}

function snapdumpOverall(result) {
  const severities = (result.checks || []).map((item) => item.severity);
  if (severities.includes("critical")) return { className: "critical", label: "Fault detected" };
  if (severities.includes("warn")) return { className: "warn", label: "Needs attention" };
  if (!severities.length || severities.includes("info") || result.coverage?.complete === false) return { className: "info", label: "Review evidence" };
  return { className: "ok", label: "No active fault evidence" };
}

function renderSnapdumpResult(result) {
  snapdumpState.result = result;
  resetSnapdumpChat();
  const overall = snapdumpOverall(result);
  const fw = result.firmware || {};
  const snapshot = result.snapshot || {};
  const pcie = result.pcie || {};
  const legacy = result.format?.id === "megaraid_legacy";
  const hasRaidInventory = legacy || ((result.operating_mode ? result.operating_mode.raid_counts_applicable : fw.mode_name === "IOPI_FW_OPMODE_RAID") && Object.hasOwn(snapshot, "ld_present"));
  const formatLabel = result.format?.label || (legacy ? "MegaRAID module format" : result.format?.id === "mpi3" ? "MPI3 section format" : "Format not reported");
  const pcieField = (speed, width) => {
    const speedText = snapdumpReported(speed); const widthText = snapdumpReported(width);
    return speedText === "Not reported" && widthText === "Not reported" ? "Not reported" : `${speedText} / width ${widthText}`;
  };
  $("#snapdump-result-title").textContent = result.filename || "SnapDump";
  $("#snapdump-result-subtitle").textContent = `${snapdumpReported(fw.board)} · ${formatLabel} · ${result.file_count || 0} text files · Trigger: ${snapdumpReported(result.trigger)}`;
  const badge = $("#snapdump-health-badge"); badge.className = `snapdump-health-badge ${overall.className}`; badge.textContent = overall.label;
  const cards = [
    ["Controller", snapdumpReported(fw.board), "Controller model"],
    ["Firmware", snapdumpReported(fw.version), `Release level: ${snapdumpReported(fw.release_level)}`],
    ["I/O queues", `${snapdumpReported(snapshot.outstanding_io)} / ${snapdumpReported(snapshot.pending_io)}`, "Outstanding / Pending"],
    hasRaidInventory
      ? ["Logical drives", snapdumpReported(snapshot.ld_present), `Degraded: ${snapdumpReported(snapshot.ld_degraded)} · Offline: ${snapdumpReported(snapshot.ld_offline)}`]
      : ["PCIe capability", pcie.max_speed_code || pcie.max_width ? `${snapdumpReported(pcie.max_speed_code)} · x${snapdumpReported(pcie.max_width)}` : "Not reported", "Max speed code / width"],
    hasRaidInventory
      ? ["Physical disks", snapdumpReported(snapshot.pd_disks), `Failed: ${snapdumpReported(snapshot.pd_failed)} · Predictive: ${snapdumpReported(snapshot.pd_predictive)}`]
      : ["Mapped slots", snapdumpReported(snapshot.mapped_slots), "Enclosure slots"],
  ];
  $("#snapdump-summary-cards").innerHTML = cards.map(([title, value, caption]) => `<article class="snapdump-summary-card"><small>${snapdumpEscape(title)}</small><strong title="${snapdumpEscape(value)}">${snapdumpEscape(value)}</strong><span>${snapdumpEscape(caption)}</span></article>`).join("");
  const checks = result.checks || [];
  $("#snapdump-check-count").textContent = `${checks.filter((item) => item.severity === "ok").length}/${checks.length} checks OK`;
  $("#snapdump-checks").innerHTML = checks.map((item) => `<div class="snapdump-check-row ${snapdumpEscape(item.severity)}"><span class="snapdump-check-icon">${item.severity === "ok" ? "✓" : item.severity === "critical" ? "×" : item.severity === "warn" ? "!" : "i"}</span><div><strong>${snapdumpEscape(item.title)}</strong><p>${snapdumpEscape(item.detail)}</p><small>${snapdumpEscape(item.evidence || "")}</small></div><b>${snapdumpSeverityLabel(item.severity)}</b></div>`).join("");
  const info = [
    ["Firmware", fw.version], ["Package", fw.package], ["Driver", fw.driver], ["Build date", fw.build_date],
    ["Release level", fw.release_level], ["Runtime", (fw.runtime_lines || []).join(" · ")],
  ];
  if (result.operating_mode) info.push(["Operating mode", result.operating_mode.name], ["Profile ID (hex)", result.operating_mode.profile_id]);
  if (hasRaidInventory) {
    info.push(["Controller resets", snapshot.controller_resets]);
    if (legacy || result.operating_mode?.external_ddr_applicable) info.push(["Correctable memory errors", snapshot.mem_correctable], ["Uncorrectable memory errors", snapshot.mem_uncorrectable]);
    if (legacy) info.push(["Host PCIe maximum", pcie.max_speed_gts != null ? `${pcie.max_speed_gts} GT/s · x${snapdumpReported(pcie.max_width)}` : "Not reported"], ["Host PCIe current", pcie.current_speed_gts != null ? `${pcie.current_speed_gts} GT/s · x${snapdumpReported(pcie.current_width)}` : "Not reported"]);
    else info.push(["Personality", fw.personality], ["fwOpMode", fw.operation_mode], ["Max PCIe code", pcieField(pcie.max_speed_code, pcie.max_width)], ["Current PCIe code", pcieField(pcie.current_speed_code, pcie.current_width)]);
    const logicalDrives = Array.isArray(result.logical_drives) ? result.logical_drives : [];
    if (logicalDrives.length) logicalDrives.forEach((drive) => {
      info.push([`Logical drive ${snapdumpReported(drive.id)}`, `RAID ${snapdumpReported(drive.raid_level)} · ${snapdumpReported(drive.state)}`]);
    });
    else info.push(["Logical drive states", "Not reported"]);
  } else {
    info.push(["Personality", fw.personality], ["fwOpMode", fw.operation_mode], ["Max PCIe code", pcieField(pcie.max_speed_code, pcie.max_width)], ["Current PCIe code", pcieField(pcie.current_speed_code, pcie.current_width)]);
  }
  $("#snapdump-info-eyebrow").textContent = hasRaidInventory ? "CONTROLLER & RAID" : "FIRMWARE & LINK";
  $("#snapdump-info-title").textContent = hasRaidInventory ? "Controller & RAID" : "Firmware & link";
  $("#snapdump-firmware").innerHTML = info.map(([label, value]) => `<div><span>${snapdumpEscape(label)}</span><strong title="${snapdumpEscape(snapdumpReported(value))}">${snapdumpEscape(snapdumpReported(value))}</strong></div>`).join("");
  const events = result.events?.events || [];
  $("#snapdump-event-count").textContent = `${Math.min(events.length, 30)} shown / ${result.events?.total_count ?? events.length} parsed · history`;
  $("#snapdump-events").innerHTML = events.length ? events.slice(-30).reverse().map((item) => `<div class="snapdump-event"><time>${snapdumpEscape(item.time)}</time><p>${snapdumpEscape(item.message)}</p></div>`).join("") : '<div class="snapdump-empty">No supported event records available.</div>';
  $("#snapdump-notes").innerHTML = (result.notes || []).map((note) => `<span>• ${snapdumpEscape(note)}</span>`).join("");
  renderSnapdumpEvidence(result);
  renderSnapdumpFiles();
  $("#snapdump-result").classList.remove("hidden");
}

function renderSnapdumpEvidence(result) {
  const root = $("#snapdump-avenger");
  const panel = $("#snapdump-avenger-panel");
  const mapping = result.device_mapping;
  const configuration = result.configuration;
  const diagnostics = result.diagnostics;
  const skipped = result.intake?.unparsed_entries || [];
  if (!mapping && !skipped.length) { panel.classList.add("hidden"); root.replaceChildren(); return; }
  panel.classList.remove("hidden");
  const e = snapdumpEscape;
  const reported = value => e(snapdumpReported(value));
  const references = [];
  const source = value => {
    if (!value?.name || !Number.isInteger(value.start_line)) return "";
    const id = references.push(value) - 1;
    return `<button type="button" class="snapdump-evidence-source" data-evidence-ref="${id}">${e(value.name)}:${value.start_line}</button>`;
  };
  const table = (headers, rows) => `<div class="snapdump-evidence-table"><table><thead><tr>${headers.map(h => `<th>${e(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const blocks = [];
  const identity = result.controller_identity;
  if (identity) blocks.push(`<div class="snapdump-evidence-block"><h4>Controller identity · ${reported(identity.generation)} · ${reported(identity.chip_role)}</h4><p>${reported(identity.chip)} · ${reported(identity.board)} · ${reported(identity.board_tracer)}</p><p>${e(identity.limitation)}</p>${(identity.evidence || []).map(source).join(" ")}</div>`);
  const functions = result.host_functions;
  if (functions) {
    const items = functions.functions || [];
    blocks.push(`<details class="snapdump-evidence-block"${items.length > 1 ? " open" : ""}><summary>Host IOC functions · ${items.length} observed instances</summary><p>${e(functions.limitation)}</p><p>${e(Object.entries(functions.summary || {}).map(([key, value]) => `${key}: ${value}`).join(" · "))}</p>${(functions.evidence || []).map(source).join(" ")}${items.length ? table(["IOC index", "Role", "Raw host fields (hex)", "Source"], items.map(f => [f.ioc_index, e(f.role), e(Object.entries(f.raw_fields || {}).map(([key, value]) => `${key}=0x${value.toString(16)}`).join(" · ")), (f.sources || []).map(source).join(" ")])) : '<p>No supported Host Interface IOC blocks were collected.</p>'}${(functions.generic_ioc_counters || []).map(g => `<p>Generic Config NumberOfIocs (raw): ${e(g.raw)} · separate scope ${source(g.source)}</p>`).join("")}</details>`);
  }
  if (mapping) {
    const mode = result.operating_mode || {};
    blocks.push(`<div class="snapdump-evidence-block"><h4>Operating mode: ${reported(mode.name)}</h4><p>Personality ${reported(mode.personality)} · Profile ${reported(mode.profile_id)} · ${reported(mode.runtime)}</p><p>${e(mode.limitation || "")}</p>${(mode.evidence || []).map(source).join(" ")}</div>`);
    const devices = mapping.devices || [];
    const ranges = mapping.ranges || [];
    blocks.push(`<details class="snapdump-evidence-block"${devices.length ? " open" : ""}><summary>Device mapping · ${devices.filter(d => d.kind === "disk").length} disks · ${devices.filter(d => d.kind === "SES").length} SES · ${ranges.length} reserved ranges</summary><p>${e(mapping.limitation)}</p>${devices.length ? table(["Persistent ID", "Kind", "Enclosure / observed slot", "Model / serial", "Range membership / ID offset", "Source"], devices.slice(0, 100).map(d => [e(d.id_hex), e(d.kind), `${d.enclosure_id == null ? "Not reported" : "0x" + d.enclosure_id.toString(16)} / ${reported(d.slot)}`, `${reported(d.model)} / ${reported(d.serial)}`, `${e(d.range_status)}${d.range_id_offset == null ? "" : " · offset " + d.range_id_offset}${d.enclosure_elid ? " · ELID " + e(d.enclosure_elid) : ""}`, (d.sources || []).map(source).join(" ")])) : '<p>No supported PD inventory records were decoded.</p>'}<p>${Math.min(devices.length, 100)} / ${devices.length} device records shown. Malformed persistent rows: ${mapping.malformed_rows || 0}.</p>${ranges.length ? table(["ELID", "First ID (hex)", "Reserved IDs / StSlot (raw)", "PHY words (hex)", "Source"], ranges.slice(0, 80).map(r => [e(r.enclosure_elid), "0x" + r.first_id.toString(16), `${r.reserved_ids} / ${r.first_slot}`, e((r.phy_bitmap_words || []).join(" ")), source(r.source)])) : ""}<p>${Math.min(ranges.length, 80)} / ${ranges.length} reserved ranges shown; reservations do not prove disk presence.</p></details>`);
  }
  if (configuration) {
    const pages = configuration.pages || [];
    const changed = configuration.current_default_differences || [];
    blocks.push(`<details class="snapdump-evidence-block"><summary>Configuration coverage · ${pages.length} page records · ${changed.length} CURRENT / DEFAULT differences</summary><p>${e(configuration.limitation)}</p><p>${e(Object.entries(configuration.regions || {}).map(([key, count]) => `${key}: ${count}`).join(" · "))}</p>${pages.length ? table(["Region", "Page / IOC / address", "Purpose", "Words captured / declared", "Source"], pages.slice(0, 80).map(p => [e(p.region), `${e(p.type)} ${p.page} / ${p.ioc} / ${e(p.address)}`, e(p.label), `${p.words_seen} / ${p.size_words}${p.collection_error ? " · collection error nearby" : ""}`, source(p.source)])) : '<p>No supported ConfigPages records were decoded.</p>'}<p>${Math.min(pages.length, 80)} / ${pages.length} raw page records shown. Fields remain undecoded.</p>${changed.length ? table(["Changed page", "Purpose", "DEFAULT / CURRENT sources"], changed.slice(0, 80).map(p => [`${e(p.type)} ${p.page} / IOC ${p.ioc} / ${e(p.address)}`, e(p.label), p.sources.map(source).join(" ")])) : ""}</details>`);
  }
  const persistent = mapping?.persistent_records || [];
  if (persistent.length) blocks.push(`<details class="snapdump-evidence-block"><summary>Persistent PD records · ${persistent.length}</summary><p>${e(mapping.persistent_record_limitation)}</p>${table(["Record index (hex)", "Unique ID (hex)", "Bad / missing / rebuild flags", "Source"], persistent.slice(0, 40).map(p => ["0x" + p.index.toString(16), p.UniqueId == null ? "Not reported" : "0x" + p.UniqueId.toString(16), [p.pdIsBad, p.pdIsMissing, p.PdRebuildNeeded].map(reported).join(" / "), source(p.source)]))}<p>${Math.min(persistent.length, 40)} / ${persistent.length} persistent records shown.</p></details>`);
  if (diagnostics) {
    const observations = diagnostics.observations || [];
    blocks.push(`<details class="snapdump-evidence-block"${observations.length ? " open" : ""}><summary>Diagnostic observations · ${diagnostics.total_matches || 0} pattern matches</summary><p>${e(diagnostics.limitation)} ${e(diagnostics.selection)}</p>${observations.length ? table(["Category", "Raw evidence", "Source"], observations.slice(-120).map(o => [e(o.kinds.join(", ")), `<pre>${e(o.source.excerpt)}</pre>`, source(o.source)])) : '<p>No supported diagnostic patterns matched the scanned text; this does not exclude a fault.</p>'}<p>${Math.min(observations.length, 120)} source lines shown.</p>${(diagnostics.recommended_evidence || []).map(t => `<p>• ${e(t)}</p>`).join("")}</details>`);
  }
  if (skipped.length) blocks.push(`<details class="snapdump-evidence-block"><summary>Collected, not decoded · ${skipped.length} archive entries</summary><p>${e(result.intake.limitation)}</p>${table(["Entry", "Bytes", "Status"], skipped.map(f => [e(f.name), f.bytes, e(f.status)]))}</details>`);
  root.innerHTML = blocks.join("");
  for (const button of root.querySelectorAll?.("[data-evidence-ref]") || []) button.addEventListener("click", () => {
    const ref = references[Number(button.dataset.evidenceRef)];
    if (ref) { loadSnapdumpFile(ref.name, ref.start_line, Math.min(ref.end_line, ref.start_line + 80)); $("#snapdump-file-explorer").scrollIntoView({behavior: "smooth", block: "start"}); }
  });
}

function renderSnapdumpFiles() {
  const result = snapdumpState.result;
  if (!result) return;
  const term = String($("#snapdump-file-filter").value || "").trim().toLowerCase();
  const files = (result.files || []).filter((item) => !term || item.name.toLowerCase().includes(term));
  $("#snapdump-files").innerHTML = files.length ? files.map((item) => `<button type="button" class="snapdump-file-item ${item.name === snapdumpState.selectedFile ? "active" : ""}" data-snapdump-file="${snapdumpEscape(item.name)}"><strong>${snapdumpEscape(item.name)}</strong><small>${formatBytes(item.bytes)}</small></button>`).join("") : '<div class="snapdump-empty">No matching files.</div>';
  $$("[data-snapdump-file]").forEach((button) => button.addEventListener("click", () => loadSnapdumpFile(button.dataset.snapdumpFile)));
}

function snapdumpFileWindow(text, startLine, endLine) {
  if (!Number.isInteger(startLine) || startLine < 1) return text;
  const first = Math.max(1, startLine - 10);
  const last = Math.min(startLine + 200, Math.max(startLine, Number.isInteger(endLine) ? endLine : startLine) + 10);
  let line = 1; let from = first === 1 ? 0 : -1; let to = text.length;
  for (const match of text.matchAll(/\r\n|\r|\n/g)) {
    line += 1;
    if (line === first) from = match.index + match[0].length;
    if (line > last) { to = match.index; break; }
  }
  if (from < 0 || line < startLine) return text;
  return `[Original log lines ${first}–${Math.min(last, line)}]\n` + text.slice(from, to);
}

async function loadSnapdumpFile(name, startLine, endLine) {
  const result = snapdumpState.result;
  if (!result || !name) return;
  snapdumpState.selectedFile = name; renderSnapdumpFiles();
  const url = result.file_urls?.[name];
  if (!url) return;
  $("#snapdump-file-preview").textContent = "Loading…";
  try {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    if (snapdumpState.result !== result || snapdumpState.selectedFile !== name) return;
    const preview = snapdumpFileWindow(text, startLine, endLine);
    $("#snapdump-file-preview").textContent = preview.slice(0, 500000) + (preview.length > 500000 ? "\n[Preview limited to 500,000 characters.]" : "");
  } catch (error) { if (snapdumpState.result === result && snapdumpState.selectedFile === name) $("#snapdump-file-preview").textContent = `Unable to read file: ${error.message}`; }
}

function chooseSnapdumpFile(file) {
  if (!file || snapdumpState.busy) return;
  const name = file.name.toLowerCase();
  if (!(name.endsWith(".zip") || name.endsWith(".txt") || name.endsWith(".log"))) { showToast("Choose a .zip, .txt or .log file."); return; }
  const maxMiB = name.endsWith(".zip") ? 50 : 16;
  if (file.size > maxMiB * 1024 * 1024) { showToast(`This file must not exceed ${maxMiB} MiB.`); return; }
  snapdumpState.file = file; $("#snapdump-filename").textContent = `${file.name} · ${formatBytes(file.size)}`; $("#snapdump-analyze").disabled = false; $("#snapdump-status").textContent = "Ready to analyze";
}

const snapdumpFileInput = $("#snapdump-file");
$("#snapdump-choose").addEventListener("click", () => snapdumpFileInput.click());
snapdumpFileInput.addEventListener("change", (event) => { chooseSnapdumpFile(event.target.files[0]); event.target.value = ""; });
const snapdumpDropzone = $("#snapdump-dropzone");
snapdumpDropzone.addEventListener("dragover", (event) => { event.preventDefault(); snapdumpDropzone.classList.add("dragover"); });
snapdumpDropzone.addEventListener("dragleave", () => snapdumpDropzone.classList.remove("dragover"));
snapdumpDropzone.addEventListener("drop", (event) => { event.preventDefault(); snapdumpDropzone.classList.remove("dragover"); chooseSnapdumpFile(event.dataTransfer.files[0]); });
snapdumpDropzone.addEventListener("keydown", (event) => {
  if (event.target === snapdumpDropzone && !snapdumpState.busy && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); snapdumpFileInput.click(); }
});
$("#snapdump-analyze").addEventListener("click", async () => {
  if (!snapdumpState.file || snapdumpState.busy) return;
  snapdumpState.busy = true;
  const generation = ++snapdumpState.generation;
  $("#snapdump-choose").disabled = true;
  $("#snapdump-result").classList.add("hidden");
  snapdumpState.result = null; snapdumpState.selectedFile = "";
  resetSnapdumpChat();
  $("#snapdump-file-filter").value = "";
  $("#snapdump-file-preview").textContent = "Select a file to view its original contents.";
  const button = $("#snapdump-analyze"); const status = $("#snapdump-status"); const error = $("#snapdump-error");
  button.disabled = true; error.classList.add("hidden"); status.textContent = "Reading and analyzing SnapDump…";
  const form = new FormData(); form.append("file", snapdumpState.file);
  try {
    const result = await api("/api/snapdump/analyze", { method: "POST", body: form });
    if (generation !== snapdumpState.generation) return;
    renderSnapdumpResult(result); status.textContent = "Analysis complete";
  } catch (requestError) {
    if (generation !== snapdumpState.generation) return;
    error.textContent = requestError.message; error.classList.remove("hidden"); status.textContent = "Analysis failed";
  } finally {
    if (generation === snapdumpState.generation) { snapdumpState.busy = false; button.disabled = false; $("#snapdump-choose").disabled = false; }
  }
});
$("#snapdump-file-filter").addEventListener("input", renderSnapdumpFiles);
function resetSnapdump() {
  snapdumpState.generation += 1;
  snapdumpState.file = null; snapdumpState.result = null; snapdumpState.selectedFile = ""; snapdumpState.busy = false;
  resetSnapdumpChat();
  $("#snapdump-result").classList.add("hidden");
  $("#snapdump-filename").textContent = "No file selected";
  $("#snapdump-status").textContent = ""; $("#snapdump-error").classList.add("hidden");
  $("#snapdump-analyze").disabled = true; $("#snapdump-choose").disabled = false;
  $("#snapdump-file-filter").value = "";
  ["#snapdump-files", "#snapdump-checks", "#snapdump-firmware", "#snapdump-events", "#snapdump-summary-cards", "#snapdump-notes", "#snapdump-avenger"].forEach(selector => $(selector).replaceChildren());
  $("#snapdump-result-title").textContent = "SnapDump"; $("#snapdump-result-subtitle").textContent = "";
  $("#snapdump-file-preview").textContent = "Select a file to view its original contents.";
}
$("#snapdump-reset").addEventListener("click", resetSnapdump);




resetSnapdump();
window.addEventListener("pagehide", () => { snapdumpChatState.controller?.abort(); });
})();
