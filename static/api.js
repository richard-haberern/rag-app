// Shared, framework-free API layer for the app shell (demo.html / app.js).
// All URLs are relative so this works same-origin anywhere (local, Docker, HF Spaces).
// The session rides an HttpOnly `session_token` cookie set by the backend; we never
// read or store it in JS. `credentials: "same-origin"` makes fetch send that cookie
// on same-origin requests — which, with the backend's SameSite=Lax + POST posture, is
// the whole CSRF story. No token scheme, no Authorization header.

(function () {
  "use strict";

  // Generation can legitimately take a while (backend LLM timeout is 60 s), so the
  // client aborts a bit above that instead of hanging forever.
  const REQUEST_TIMEOUT_MS = 90_000;

  // Error carrying the HTTP status plus the server's {"detail": ...} message, so
  // callers can branch on status and show specific copy.
  class ApiError extends Error {
    constructor(status, detail) {
      super(detail || `Request failed with status ${status}`);
      this.status = status;
    }
  }

  // Parse a FastAPI error body into a message. {"detail": string} for HTTPException,
  // {"detail": [ {...,"msg": ...} ]} for 422 validation.
  async function detailFrom(resp) {
    try {
      const data = await resp.json();
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) return data.detail.map((d) => d.msg).join("; ");
    } catch {
      // non-JSON error body (e.g. a bare 500) — no detail
    }
    return "";
  }

  async function request(method, url, body) {
    const init = {
      method,
      credentials: "same-origin",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(url, init);
    } catch (err) {
      if (err.name === "TimeoutError") {
        throw new ApiError(0, "The request timed out — the server may be busy. Try again.");
      }
      throw new ApiError(0, "Can't reach the API — is the server running?");
    }
    if (!resp.ok) throw new ApiError(resp.status, await detailFrom(resp));
    if (resp.status === 204) return null;
    return resp.json();
  }

  const postJSON = (url, body) => request("POST", url, body ?? {});
  const getJSON = (url) => request("GET", url);
  const del = (url) => request("DELETE", url);

  // ---- typed endpoint wrappers (exact paths/shapes verified against the routers) ----

  const API = {
    ApiError,
    postJSON,
    getJSON,

    // Auth / session
    whoami: () => getJSON("/auth/me"), // 200 {authenticated, username} | throws 401
    register: (username, password) => postJSON("/register", { username, password }),
    login: (username, password) => postJSON("/login", { username, password }),
    anonymousLogin: () => postJSON("/anonymous_login"),
    logout: () => postJSON("/logout"),
    logoutEverywhere: () => postJSON("/logout_everywhere"),
    deleteAccount: () => postJSON("/delete_account"),

    // Documents
    listDocuments: () => getJSON("/query/stored_documents/metadata"), // [{filename, doc_id, doc_metadata}]
    deleteDocument: (docId) => del("/delete/" + encodeURIComponent(docId)), // 204
    ingest: (content, filename) => postJSON("/store", { content, filename, metadata: {} }), // -> uuid

    // Query
    retrieve: (query) => postJSON("/query/retrieve", { query }), // -> [str]
    generate: (query) => postJSON("/query/generate", { query }), // -> str
  };

  window.API = API;
})();
