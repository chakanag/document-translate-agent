// ── WebAuthn 지원 여부 확인 ──────────────────────────────────────────
if (!window.PublicKeyCredential) {
  document.getElementById("noPasskey").style.display = "block";
}

// ── 탭 전환 ─────────────────────────────────────────────────────────
document.querySelectorAll(".auth-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const target = tab.dataset.tab;
    document.querySelectorAll(".auth-tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".auth-form").forEach((f) => f.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById(target + "Form").classList.add("active");
    document.getElementById(target + "Msg").textContent = "";
  });
});

// ── 유틸 ─────────────────────────────────────────────────────────────
function b64url(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=/g, "");
}

function fromB64url(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4) str += "=";
  const bin = atob(str);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

function setMsg(id, text, isError = false) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.className = "auth-msg " + (isError ? "error" : text ? "ok" : "");
}

function setLoading(btnId, loading) {
  document.getElementById(btnId).disabled = loading;
}

// ── 회원가입 ─────────────────────────────────────────────────────────
document.getElementById("registerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("regUsername").value.trim();
  const email = document.getElementById("regEmail").value.trim();

  setMsg("registerMsg", "패스키 등록을 시작합니다...");
  setLoading("registerBtn", true);

  try {
    // 1. 등록 옵션 요청
    const beginRes = await fetch("/api/auth/register/begin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email }),
    });
    const beginData = await beginRes.json();
    if (!beginRes.ok) throw new Error(beginData.error || "등록 시작 실패");

    const challenge = beginData.challenge;
    const userId = beginData._userId;

    // 2. 브라우저 패스키 생성
    const credOptions = {
      publicKey: {
        ...beginData,
        challenge: fromB64url(beginData.challenge),
        user: {
          ...beginData.user,
          id: fromB64url(beginData.user.id),
        },
        excludeCredentials: (beginData.excludeCredentials || []).map((c) => ({
          ...c,
          id: fromB64url(c.id),
        })),
      },
    };

    setMsg("registerMsg", "패스키를 생성하세요 (지문/Face ID)...");
    const credential = await navigator.credentials.create(credOptions);

    // 3. 등록 완료
    const credPayload = {
      id: credential.id,
      rawId: b64url(credential.rawId),
      type: credential.type,
      response: {
        clientDataJSON: b64url(credential.response.clientDataJSON),
        attestationObject: b64url(credential.response.attestationObject),
      },
    };

    const completeRes = await fetch("/api/auth/register/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email, challenge, credential: credPayload }),
    });
    const completeData = await completeRes.json();
    if (!completeRes.ok) throw new Error(completeData.error || "등록 완료 실패");

    if (completeData.pending) {
      // 승인 대기 상태 — 로그인 탭으로 전환하지 않고 안내 메시지 표시
      document.getElementById("registerForm").style.display = "none";
      setMsg("registerMsg",
        "✅ 패스키 등록 완료! 관리자 승인 후 로그인하실 수 있습니다.<br>" +
        "승인이 완료되면 로그인 탭에서 패스키로 로그인하세요.");
    } else {
      setMsg("registerMsg", "✅ 가입 완료! 메인 화면으로 이동합니다...");
      setTimeout(() => { location.href = "/"; }, 1200);
    }
  } catch (err) {
    setMsg("registerMsg", err.message || "오류가 발생했습니다", true);
    setLoading("registerBtn", false);
  }
});

// ── 로그인 ───────────────────────────────────────────────────────────
document.getElementById("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();

  setMsg("loginMsg", "패스키 인증을 시작합니다...");
  setLoading("loginBtn", true);

  try {
    // 1. 인증 옵션 요청
    const beginRes = await fetch("/api/auth/login/begin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username }),
    });
    const beginData = await beginRes.json();
    if (!beginRes.ok) {
      if (beginRes.status === 403 && beginData.pending) {
        setMsg("loginMsg",
          "⏳ 아직 관리자 승인 대기 중입니다.<br>승인 후 다시 시도해 주세요.", true);
        setLoading("loginBtn", false);
        return;
      }
      throw new Error(beginData.error || "로그인 시작 실패");
    }

    const challenge = beginData.challenge;

    // 2. 브라우저 패스키 인증
    const assertionOptions = {
      publicKey: {
        ...beginData,
        challenge: fromB64url(beginData.challenge),
        allowCredentials: (beginData.allowCredentials || []).map((c) => ({
          ...c,
          id: fromB64url(c.id),
        })),
      },
    };

    setMsg("loginMsg", "패스키로 인증하세요 (지문/Face ID)...");
    const assertion = await navigator.credentials.get(assertionOptions);

    // 3. 로그인 완료
    const assertPayload = {
      id: assertion.id,
      rawId: b64url(assertion.rawId),
      type: assertion.type,
      response: {
        clientDataJSON: b64url(assertion.response.clientDataJSON),
        authenticatorData: b64url(assertion.response.authenticatorData),
        signature: b64url(assertion.response.signature),
        userHandle: assertion.response.userHandle ? b64url(assertion.response.userHandle) : null,
      },
    };

    const completeRes = await fetch("/api/auth/login/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, challenge, credential: assertPayload }),
    });
    const completeData = await completeRes.json();
    if (!completeRes.ok) throw new Error(completeData.error || "로그인 실패");

    setMsg("loginMsg", "✅ 로그인 성공! 이동합니다...");
    setTimeout(() => { location.href = "/"; }, 800);
  } catch (err) {
    if (err.name === "NotAllowedError") {
      setMsg("loginMsg", "패스키 인증이 취소되었습니다", true);
    } else {
      setMsg("loginMsg", err.message || "오류가 발생했습니다", true);
    }
    setLoading("loginBtn", false);
  }
});
