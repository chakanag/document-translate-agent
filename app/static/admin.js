// ── 초기화 ─────────────────────────────────────────────────────────
let currentUser = null;

async function init() {
  const res = await fetch("/api/auth/me");
  if (!res.ok) { location.href = "/static/auth.html"; return; }
  const { user } = await res.json();
  if (user.role !== "admin") { location.href = "/"; return; }
  currentUser = user;
  document.getElementById("adminUserInfo").textContent = `${user.username} 으로 로그인 중`;
  loadStats();
  loadUsers();
  loadJobs();
}

// ── 통계 ────────────────────────────────────────────────────────────
async function loadStats() {
  const res = await fetch("/api/admin/stats");
  if (!res.ok) return;
  const d = await res.json();
  document.getElementById("statUsers").textContent = d.totalUsers;
  document.getElementById("statActiveUsers").textContent = d.activeUsers;
  document.getElementById("statJobs").textContent = d.totalJobs;
  const completed = d.jobsByStatus?.completed || 0;
  document.getElementById("statCompleted").textContent = completed;
  const rate = d.totalJobs ? Math.round((completed / d.totalJobs) * 100) : 0;
  document.getElementById("statSuccessRate").textContent = d.totalJobs ? `성공률 ${rate}%` : "";
  document.getElementById("statStorage").textContent = d.storageUsedMb;
}

// ── 유저 목록 ────────────────────────────────────────────────────────
async function loadUsers() {
  const tbody = document.getElementById("usersBody");
  const res = await fetch("/api/admin/users");
  if (!res.ok) { tbody.innerHTML = `<tr class="empty-row"><td colspan="6">불러오기 실패</td></tr>`; return; }
  const { users } = await res.json();
  if (!users.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">유저가 없습니다</td></tr>`;
    return;
  }
  tbody.innerHTML = users.map((u) => `
    <tr data-id="${u.id}">
      <td><strong>${esc(u.username)}</strong></td>
      <td>${esc(u.email || "—")}</td>
      <td><span class="role-badge role-${u.role}">${u.role}</span></td>
      <td><span class="${u.isActive ? "status-active" : "status-inactive"}">${u.isActive ? "활성" : "비활성"}</span></td>
      <td>${fmtDate(u.createdAt)}</td>
      <td>
        ${u.id !== currentUser?.id ? `
          <button class="action-btn"
            data-action="toggle-role"
            data-id="${u.id}"
            data-role="${u.role}">
            ${u.role === "admin" ? "일반 유저로" : "Admin으로"}
          </button>
          <button class="action-btn"
            data-action="toggle-active"
            data-id="${u.id}"
            data-active="${u.isActive}">
            ${u.isActive ? "비활성화" : "활성화"}
          </button>
          <button class="action-btn danger"
            data-action="remove-user"
            data-id="${u.id}"
            data-username="${esc(u.username)}">삭제</button>
        ` : `<span style="color:var(--muted);font-size:12px">(본인)</span>`}
      </td>
    </tr>
  `).join("");
}

async function toggleRole(userId, currentRole) {
  const newRole = currentRole === "admin" ? "user" : "admin";
  if (!confirm(`역할을 '${newRole}'으로 변경할까요?`)) return;
  const res = await fetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role: newRole }),
  });
  const d = await res.json();
  if (!res.ok) { alert(d.error || "변경 실패"); return; }
  loadUsers();
}

async function toggleActive(userId, isActive) {
  const res = await fetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ isActive: !isActive }),
  });
  if (!res.ok) { const d = await res.json(); alert(d.error || "변경 실패"); return; }
  loadUsers();
}

async function removeUser(userId, username) {
  if (!confirm(`'${username}' 계정을 삭제할까요? 복구할 수 없습니다.`)) return;
  const res = await fetch(`/api/admin/users/${userId}`, { method: "DELETE" });
  if (!res.ok) { const d = await res.json(); alert(d.error || "삭제 실패"); return; }
  loadUsers();
  loadJobs();
  loadStats();
}

// ── 번역 작업 목록 ───────────────────────────────────────────────────
async function loadJobs() {
  const tbody = document.getElementById("jobsBody");
  const res = await fetch("/api/admin/jobs");
  if (!res.ok) { tbody.innerHTML = `<tr class="empty-row"><td colspan="6">불러오기 실패</td></tr>`; return; }
  const { jobs } = await res.json();
  if (!jobs.length) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">번역 작업이 없습니다</td></tr>`;
    return;
  }
  tbody.innerHTML = jobs.map((j) => `
    <tr>
      <td title="${esc(j.originalFileName)}">${esc(truncate(j.originalFileName, 28))}</td>
      <td>${esc(j.userId || "—")}</td>
      <td>${esc(j.sourceLanguage || "??")} → ${esc(j.targetLanguage)}</td>
      <td><span class="job-status ${j.status}">${j.status}</span></td>
      <td>${fmtDate(j.createdAt)}</td>
      <td>
        <button class="action-btn danger"
          data-action="remove-job"
          data-id="${j.id}">삭제</button>
      </td>
    </tr>
  `).join("");
}

async function removeJob(jobId) {
  if (!confirm("이 번역 작업을 삭제할까요?")) return;
  const res = await fetch(`/api/admin/jobs/${jobId}`, { method: "DELETE" });
  if (!res.ok) { const d = await res.json(); alert(d.error || "삭제 실패"); return; }
  loadJobs();
  loadStats();
}

// ── 이벤트 위임 (CSP 'unsafe-inline' 없이 동작) ──────────────────────
document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;

  const action  = btn.dataset.action;
  const id      = btn.dataset.id;

  if (action === "toggle-role")   toggleRole(id, btn.dataset.role);
  if (action === "toggle-active") toggleActive(id, btn.dataset.active === "true");
  if (action === "remove-user")   removeUser(id, btn.dataset.username);
  if (action === "remove-job")    removeJob(id);
});

// ── 로그아웃 ─────────────────────────────────────────────────────────
document.getElementById("logoutBtn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.href = "/static/auth.html";
});

// ── 새로고침 버튼 ────────────────────────────────────────────────────
document.getElementById("refreshUsers").addEventListener("click", loadUsers);
document.getElementById("refreshJobs").addEventListener("click", () => { loadJobs(); loadStats(); });

// ── 유틸 ─────────────────────────────────────────────────────────────
function esc(str) {
  return String(str ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}
function truncate(str, max) {
  return str.length > max ? str.slice(0, max) + "…" : str;
}

init();
