"use strict";

const state = { csrfToken: "", projects: [], candidates: [] };

function $(id) {
  return document.getElementById(id);
}

function setText(node, value) {
  node.textContent = value == null ? "" : String(value);
}

async function api(path, options = {}) {
  const headers = Object.assign({ "Accept": "application/json" }, options.headers || {});
  if (options.body) headers["Content-Type"] = "application/json";
  if (["POST", "PATCH"].includes(options.method)) headers["X-CSRF-Token"] = state.csrfToken;
  const res = await fetch(path, Object.assign({ credentials: "same-origin", headers }, options));
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  const type = res.headers.get("Content-Type") || "";
  if (options.download) return res.blob();
  return type.includes("application/json") ? res.json() : res.text();
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function switchView(name) {
  document.querySelectorAll(".view").forEach((view) => view.classList.add("hidden"));
  $(name).classList.remove("hidden");
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === name));
}

function field(label, value) {
  const p = document.createElement("p");
  setText(p, `${label}: ${value || "-"}`);
  return p;
}

function card(title, details) {
  const article = document.createElement("article");
  article.className = "card";
  const h = document.createElement("h3");
  setText(h, title);
  const p = document.createElement("p");
  setText(p, details);
  article.append(h, p);
  return article;
}

function input(value, label) {
  const el = document.createElement("input");
  el.value = value || "";
  el.setAttribute("aria-label", label);
  return el;
}

function select(value, values, label) {
  const el = document.createElement("select");
  el.setAttribute("aria-label", label);
  values.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item;
    setText(opt, item);
    el.append(opt);
  });
  el.value = value || values[0];
  return el;
}

async function loadBootstrap() {
  const data = await api("/api/bootstrap");
  state.csrfToken = data.csrfToken;
  setText($("storageRoot"), Object.values(data.dataLocations).join(", "));
  setText($("detectedProfiles"), data.profiles.length ? data.profiles.map((p) => `${p.id} schema ${p.schemaVersion || "unsupported"}`).join(", ") : "감지된 프로필 없음");
  setText($("kanbanState"), data.kanban ? "감지됨" : "없음");
  if (data.disclosureAccepted) {
    $("app").classList.remove("hidden");
    await refreshAll();
  } else {
    $("firstRun").classList.remove("hidden");
  }
}

async function acceptDisclosure() {
  await api("/api/disclosure/accept", { method: "POST", body: "{}" });
  $("firstRun").classList.add("hidden");
  $("app").classList.remove("hidden");
  await refreshAll();
}

async function refreshAll() {
  await loadProjects();
  await loadSessions();
  await loadSkills();
  await loadCandidates();
  await loadDiagnostics();
}

async function loadProjects() {
  const data = await api("/api/projects");
  state.projects = data.projects;
  const root = $("projects");
  const today = $("todayList");
  root.replaceChildren();
  today.replaceChildren();
  data.projects.filter((p) => !p.archived).forEach((project) => {
    const node = projectEditor(project);
    root.append(node);
    if (project.pinned || project.nextAction) today.append(card(project.name, project.nextAction || "다음 작업 없음"));
  });
  if (!today.children.length) today.append(card("오늘의 실행목록", "고정되었거나 다음 작업이 있는 프로젝트가 없습니다."));
}

function projectEditor(project) {
  const node = card(project.name, `${project.status || "active"} · ${project.priority || "normal"}`);
  const name = input(project.name, "이름");
  const status = select(project.status, ["active", "waiting", "done", "archived"], "상태");
  const priority = select(project.priority, ["low", "normal", "high", "urgent"], "우선순위");
  const dueDate = input(project.dueDate, "마감일");
  const ownerProfile = input(project.ownerProfile, "담당 프로필");
  const nextAction = input(project.nextAction, "다음 작업");
  const pinned = document.createElement("input");
  pinned.type = "checkbox";
  pinned.checked = Boolean(project.pinned);
  const save = document.createElement("button");
  save.type = "button";
  setText(save, "저장");
  save.addEventListener("click", async () => {
    await api(`/api/projects/${encodeURIComponent(project.id)}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: name.value,
        status: status.value,
        priority: priority.value,
        dueDate: dueDate.value || null,
        ownerProfile: ownerProfile.value || null,
        nextAction: nextAction.value,
        pinned: pinned.checked,
      }),
    });
    await loadProjects();
  });
  const archive = document.createElement("button");
  archive.type = "button";
  setText(archive, "보관");
  archive.addEventListener("click", async () => {
    await api(`/api/projects/${encodeURIComponent(project.id)}`, { method: "PATCH", body: JSON.stringify({ archived: true }) });
    await loadProjects();
  });
  const pinLabel = document.createElement("label");
  pinLabel.append(pinned, document.createTextNode(" 고정"));
  node.append(name, status, priority, dueDate, ownerProfile, nextAction, pinLabel, save, archive);
  return node;
}

async function loadCandidates() {
  const data = await api("/api/candidates");
  state.candidates = data.candidates;
  const root = $("candidates");
  root.replaceChildren();
  if (!data.candidates.length) {
    root.append(card("연결 후보 없음", "워크스페이스 이름 기준 후보가 없습니다."));
    return;
  }
  data.candidates.forEach((candidate, index) => {
    const node = card(candidate.title || candidate.workspaceName, `${candidate.type} · ${candidate.workspaceName || "워크스페이스 없음"} · 미확정`);
    const project = select(state.projects[0] ? state.projects[0].id : "", state.projects.map((p) => p.id), "프로젝트 선택");
    const confirm = document.createElement("button");
    confirm.type = "button";
    setText(confirm, "연결 확인");
    confirm.disabled = !state.projects.length;
    confirm.addEventListener("click", async () => {
      await api("/api/candidates/confirm", { method: "POST", body: JSON.stringify({ projectId: project.value, candidate: state.candidates[index] }) });
      await loadProjects();
    });
    node.append(project, confirm);
    root.append(node);
  });
}

async function loadSessions(query = "") {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if ($("profileFilter") && $("profileFilter").value) params.set("profile", $("profileFilter").value);
  if ($("sourceFilter") && $("sourceFilter").value) params.set("source", $("sourceFilter").value);
  if ($("fromFilter") && $("fromFilter").value) params.set("from", $("fromFilter").value);
  if ($("toFilter") && $("toFilter").value) params.set("to", $("toFilter").value);
  if ($("contentSearch") && $("contentSearch").checked) params.set("content", "true");
  const data = await api(`/api/sessions?${params.toString()}`);
  renderSessions($("sessionList"), data.sessions);
  renderSessions($("recentHomeSessions"), data.sessions.slice(0, 5));
}

function renderSessions(list, sessions) {
  list.replaceChildren();
  sessions.forEach((session) => {
    const node = card(session.title || session.id, `${session.profile_id} · ${session.source || "-"} · ${session.last_activity_at || session.started_at} · 메시지 ${session.message_count || 0}`);
    node.append(field("워크스페이스", session.workspaceName || ""));
    const expand = document.createElement("button");
    expand.type = "button";
    setText(expand, "메시지 보기");
    let messagePre = null;
    let loadingMessages = false;
    expand.addEventListener("click", async () => {
      if (loadingMessages) return;
      if (messagePre && messagePre.parentNode) {
        messagePre.remove();
        setText(expand, "메시지 보기");
        return;
      }
      if (!messagePre) {
        loadingMessages = true;
        try {
          const msgs = await api(`/api/messages?profile=${encodeURIComponent(session.profile_id)}&sessionId=${encodeURIComponent(session.id)}`);
          messagePre = document.createElement("pre");
          setText(messagePre, msgs.messages.map((m) => `${m.role}: ${m.content}`).join("\n"));
        } finally {
          loadingMessages = false;
        }
      }
      node.append(messagePre);
      setText(expand, "메시지 접기");
    });
    const open = document.createElement("button");
    open.type = "button";
    setText(open, "Open in Hermes");
    open.addEventListener("click", async () => {
      const payload = await api(`/api/open-url?profile=${encodeURIComponent(session.profile_id)}&sessionId=${encodeURIComponent(session.id)}`);
      location.href = payload.url;
    });
    node.append(expand, open);
    list.append(node);
  });
}

async function loadSkills(query = "") {
  const data = await api(`/api/skills?q=${encodeURIComponent(query)}`);
  const list = $("skillList");
  list.replaceChildren();
  if (!data.results.length) {
    list.append(card("스킬 없음", "현재 감지된 읽기 전용 Skills가 없거나 검색 결과가 없습니다."));
    return;
  }
  data.results.forEach((skill) => {
    const tags = skill.tags && skill.tags.length ? ` · ${skill.tags.join(", ")}` : "";
    const category = skill.category ? ` · ${skill.category}` : "";
    const node = card(skill.name, `${skill.profile}${category}${tags}\n${skill.description || skill.snippet || ""}`);
    const preview = document.createElement("button");
    preview.type = "button";
    setText(preview, "미리보기");
    preview.addEventListener("click", async () => {
      const payload = await api(`/api/skills/${encodeURIComponent(skill.id)}`);
      setText($("skillPreview"), payload.preview || "표시할 내용이 없습니다.");
    });
    node.append(preview);
    list.append(node);
  });
}

async function loadKanban() {
  const params = new URLSearchParams();
  if ($("kanbanStatus").value) params.set("status", $("kanbanStatus").value);
  if ($("kanbanAssignee").value) params.set("assignee", $("kanbanAssignee").value);
  const data = await api(`/api/kanban?${params.toString()}`);
  const list = $("kanbanList");
  list.replaceChildren();
  setText($("kanbanNotice"), data.tasks.length ? "읽기 전용 메타데이터입니다." : "Kanban DB가 없거나 표시할 항목이 없습니다.");
  data.tasks.forEach((task) => list.append(card(task.title || task.id, `${task.status || "-"} · ${task.priority || "-"} · ${task.assignee || "-"}`)));
}

async function loadDiagnostics() {
  const data = await api("/api/diagnostics/summary");
  const root = $("diagSummary");
  root.replaceChildren();
  Object.keys(data).forEach((key) => {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    setText(dt, key);
    setText(dd, Array.isArray(data[key]) ? data[key].join(", ") : JSON.stringify(data[key]));
    root.append(dt, dd);
  });
}

async function createProject() {
  const name = $("projectName").value.trim();
  if (!name) return;
  await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
  $("projectName").value = "";
  await loadProjects();
  await loadCandidates();
}

function bind() {
  $("confirmStart").addEventListener("click", acceptDisclosure);
  $("createProject").addEventListener("click", createProject);
  $("runSearch").addEventListener("click", () => loadSessions($("searchBox").value));
  $("runSkillSearch").addEventListener("click", () => loadSkills($("skillSearchBox").value));
  $("loadKanban").addEventListener("click", loadKanban);
  $("downloadRegistry").addEventListener("click", async () => downloadBlob(await api("/api/registry/export", { download: true }), "registry-export.json"));
  $("restoreRegistry").addEventListener("click", async () => {
    await api("/api/registry/restore", { method: "POST", body: JSON.stringify({ registryJson: $("restoreText").value }) });
    await loadProjects();
  });
  $("makeDiag").addEventListener("click", async () => downloadBlob(await api("/api/diagnostics/zip", { method: "POST", body: "{}", download: true }), "diagnostics-redacted.zip"));
  $("showReceipt").addEventListener("click", async () => downloadBlob(await api("/api/diagnostics/receipt", { method: "POST", body: "{}", download: true }), "pilot-receipt.txt"));
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchView(tab.dataset.view)));
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderSessions };
}

if (typeof document !== "undefined") {
  bind();
  loadBootstrap().catch((err) => setText($("detectedProfiles"), err.message));
}
