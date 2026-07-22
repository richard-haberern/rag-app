// Groundwork app shell. On load it detects iframe embedding, then asks the backend
// "who am I" (GET /auth/me) and mounts exactly ONE of three distinct views by session
// state: logged-out, anonymous, or registered. The anonymous session and the "demo"
// are one and the same — "Continue anonymously" mints a session and drops you into the
// working app. The session lives only in the HttpOnly cookie; nothing is kept in JS
// storage. All backend calls go through window.API (api.js).

(function () {
  "use strict";

  const { API } = window;

  // ---------- tiny DOM helper (vanilla hyperscript) ----------

  function el(tag, props, ...kids) {
    const node = document.createElement(tag);
    if (props) {
      for (const [k, v] of Object.entries(props)) {
        if (v == null || v === false) continue;
        if (k === "class") node.className = v;
        else if (k === "onclick") node.addEventListener("click", v);
        else if (k === "onsubmit") node.addEventListener("submit", v);
        else if (k === "oninput") node.addEventListener("input", v);
        else if (k in node) node[k] = v;
        else node.setAttribute(k, v);
      }
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      node.append(kid.nodeType ? kid : document.createTextNode(kid));
    }
    return node;
  }

  const appRoot = () => document.getElementById("app");
  function mount(node) {
    const root = appRoot();
    root.replaceChildren(node);
    // keep focus predictable across view swaps
    const focusable = root.querySelector("[autofocus], input, button, a");
    if (focusable) focusable.focus({ preventScroll: true });
  }

  // ---------- status helper (mirrors the demo's .status pattern) ----------

  function setStatus(node, kind, text) {
    node.className = "status" + (kind ? " " + kind : "");
    if (kind === "loading") {
      node.replaceChildren(
        el("span", { class: "spinner", "aria-hidden": "true" }),
        document.createTextNode(text)
      );
    } else {
      node.textContent = text;
    }
  }

  // transient top-of-page notice for post-action feedback (errors/success)
  let toastTimer = null;
  function toast(text, kind) {
    const region = document.getElementById("toast");
    region.className = "toast" + (kind ? " " + kind : "");
    region.textContent = text;
    region.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      region.hidden = true;
    }, 5000);
  }

  // ---------- modal confirm (returns a Promise<boolean>) ----------
  // requireText: when set, the confirm button stays disabled until the user types it
  // exactly (used to make "delete account" a deliberate two-step action).

  function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false, requireText = null }) {
    return new Promise((resolve) => {
      const previouslyFocused = document.activeElement;

      function close(result) {
        document.removeEventListener("keydown", onKey);
        overlay.remove();
        if (previouslyFocused && previouslyFocused.focus) previouslyFocused.focus({ preventScroll: true });
        resolve(result);
      }
      function onKey(e) {
        if (e.key === "Escape") close(false);
      }

      const confirmBtn = el(
        "button",
        {
          class: "btn " + (danger ? "btn-danger" : "btn-primary"),
          type: "button",
          disabled: requireText ? true : false,
          onclick: () => close(true),
        },
        confirmLabel
      );

      const bodyKids = [
        el("h2", { id: "modal-title" }, title),
        typeof message === "string" ? el("p", null, message) : message,
      ];

      if (requireText) {
        bodyKids.push(
          el("label", { class: "modal-confirm-label", for: "modal-confirm-input" },
            ["Type ", el("code", null, requireText), " to confirm."]),
          el("input", {
            id: "modal-confirm-input",
            type: "text",
            autocomplete: "off",
            autocapitalize: "off",
            spellcheck: "false",
            oninput: (e) => {
              confirmBtn.disabled = e.target.value !== requireText;
            },
          })
        );
      }

      bodyKids.push(
        el("div", { class: "modal-actions" },
          el("button", { class: "btn btn-secondary", type: "button", onclick: () => close(false) }, "Cancel"),
          confirmBtn)
      );

      const dialog = el("div", {
        class: "modal",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "modal-title",
      }, ...bodyKids);

      const overlay = el("div", {
        class: "modal-overlay",
        onclick: (e) => { if (e.target === overlay) close(false); },
      }, dialog);

      document.addEventListener("keydown", onKey);
      document.body.append(overlay);
      (requireText ? dialog.querySelector("input") : confirmBtn).focus({ preventScroll: true });
    });
  }

  // ---------- shared workspace: ingest + ask + documents ----------
  // Used by both the anonymous and registered views (identical capability — both have a
  // valid session and are RLS-scoped to their own owner). Returns the node plus a
  // refreshDocs() so callers can populate the document list after mounting.

  function buildWorkspace() {
    // -- ingest --
    const ingestFilename = el("input", { id: "ingest-filename", type: "text", required: true, placeholder: "notes.txt", autocomplete: "off" });
    const ingestContent = el("textarea", { id: "ingest-content", required: true, placeholder: "Paste a few paragraphs of text you want to ask questions about…" });
    const ingestBtn = el("button", { class: "btn btn-primary", type: "submit" }, "Ingest");
    const ingestStatus = el("p", { class: "status", role: "status", "aria-live": "polite" });

    const ingestForm = el("form", {
      onsubmit: async (e) => {
        e.preventDefault();
        ingestBtn.disabled = true;
        setStatus(ingestStatus, "loading", "Chunking and embedding…");
        try {
          const docId = await API.ingest(ingestContent.value, ingestFilename.value);
          setStatus(ingestStatus, "success", "Stored. Document id: ");
          ingestStatus.append(el("span", { class: "doc-id" }, docId));
          ingestForm.reset();
          refreshDocs();
        } catch (err) {
          setStatus(ingestStatus, "error", ingestErrorText(err));
        } finally {
          ingestBtn.disabled = false;
        }
      },
    },
      el("label", { for: "ingest-filename" }, "Document name"), ingestFilename,
      el("label", { for: "ingest-content" }, "Content"), ingestContent,
      ingestBtn);

    const ingestSection = el("section", { "aria-labelledby": "ingest-heading" },
      el("h2", { id: "ingest-heading" }, "Add a document"),
      el("p", { class: "hint" }, "Paste any text — it gets chunked, embedded locally, and stored with its vectors under your session."),
      el("div", { class: "card" }, ingestForm, ingestStatus));

    // -- ask --
    const queryInput = el("input", { id: "query-input", type: "text", required: true, autocomplete: "off", placeholder: "What does the document say about…?" });
    const queryBtn = el("button", { class: "btn btn-primary", type: "submit" }, "Ask");
    const chunksStatus = el("p", { class: "status", role: "status", "aria-live": "polite" });
    const chunkList = el("ol", { class: "chunk-list" });
    const answerStatus = el("p", { class: "status", role: "status", "aria-live": "polite" });
    const answerBody = el("p", { class: "answer-body" });

    async function showChunks(query) {
      try {
        const chunks = await API.retrieve(query);
        if (chunks.length === 0) {
          setStatus(chunksStatus, "error", "No chunks passed the similarity threshold — add something related to the question first.");
          return;
        }
        setStatus(chunksStatus, "", "");
        chunks.forEach((text, i) => {
          chunkList.append(el("li", null, el("span", { class: "chunk-rank" }, "#" + (i + 1)), document.createTextNode(text)));
        });
      } catch (err) {
        setStatus(chunksStatus, "error", queryErrorText(err, "retrieval"));
      }
    }
    async function showAnswer(query) {
      try {
        const answer = await API.generate(query);
        setStatus(answerStatus, "", "");
        answerBody.textContent = answer;
      } catch (err) {
        setStatus(answerStatus, "error", queryErrorText(err, "generation"));
      }
    }

    const queryForm = el("form", {
      onsubmit: async (e) => {
        e.preventDefault();
        const query = queryInput.value;
        queryBtn.disabled = true;
        chunkList.replaceChildren();
        answerBody.textContent = "";
        setStatus(chunksStatus, "loading", "Searching vectors…");
        setStatus(answerStatus, "loading", "Retrieving + generating (the LLM can take a while)…");
        await Promise.allSettled([showChunks(query), showAnswer(query)]);
        queryBtn.disabled = false;
      },
    },
      el("label", { for: "query-input" }, "Question"), queryInput, queryBtn);

    const askSection = el("section", { "aria-labelledby": "query-heading" },
      el("h2", { id: "query-heading" }, "Ask a question"),
      el("p", { class: "hint" }, "Your question is embedded and matched against every stored chunk. The retrieved chunks are the exact context the LLM answers from."),
      el("div", { class: "card" }, queryForm,
        el("div", { class: "results" },
          el("div", null, el("h3", null, "Retrieved chunks"), chunksStatus, chunkList),
          el("div", null, el("h3", null, "Answer"), answerStatus, answerBody))));

    // -- documents --
    const docStatus = el("p", { class: "status", role: "status", "aria-live": "polite" });
    const docList = el("ul", { class: "doc-list" });

    async function refreshDocs() {
      setStatus(docStatus, "loading", "Loading your documents…");
      docList.replaceChildren();
      try {
        const docs = await API.listDocuments();
        setStatus(docStatus, "", "");
        if (docs.length === 0) {
          docStatus.className = "status";
          docStatus.textContent = "No documents yet — add one above.";
          return;
        }
        for (const doc of docs) docList.append(docRow(doc, refreshDocs));
      } catch (err) {
        setStatus(docStatus, "error", err.status === 401 ? "Your session has expired — reload the page." : (err.message || "Couldn't load documents."));
      }
    }

    const docsSection = el("section", { "aria-labelledby": "docs-heading" },
      el("h2", { id: "docs-heading" }, "Your documents"),
      el("p", { class: "hint" }, "Everything stored under your current session. Deleting a document removes its chunks and vectors too."),
      el("div", { class: "card" }, docStatus, docList));

    const node = el("div", null, ingestSection, askSection, docsSection);
    return { node, refreshDocs };
  }

  function docRow(doc, refreshDocs) {
    const metaEntries = doc.doc_metadata && typeof doc.doc_metadata === "object" ? Object.entries(doc.doc_metadata) : [];
    const delBtn = el("button", {
      class: "btn btn-danger btn-sm",
      type: "button",
      onclick: async () => {
        const ok = await confirmDialog({
          title: "Delete this document?",
          message: `“${doc.filename}” and its chunks and vectors will be permanently removed.`,
          confirmLabel: "Delete",
          danger: true,
        });
        if (!ok) return;
        try {
          await API.deleteDocument(doc.doc_id);
          refreshDocs();
          toast("Document deleted.", "success");
        } catch (err) {
          toast(err.status === 404 ? "That document no longer exists." : (err.message || "Delete failed."), "error");
        }
      },
    }, "Delete");

    return el("li", { class: "doc-row" },
      el("div", { class: "doc-main" },
        el("span", { class: "doc-name" }, doc.filename || "(untitled)"),
        el("span", { class: "doc-id", title: String(doc.doc_id) }, String(doc.doc_id)),
        metaEntries.length
          ? el("span", { class: "doc-meta" }, metaEntries.map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · "))
          : null),
      delBtn);
  }

  // ---------- error copy ----------

  function ingestErrorText(err) {
    if (err.status === 401) return "Your session has expired — reload the page.";
    if (err.status === 409) return "That exact document is already stored.";
    if (err.status === 413) return "That document is too large.";
    if (err.status === 400 || err.status === 422) return "Rejected: " + (err.message || "invalid input.");
    if (err.status >= 500) return "Server error while ingesting. Try again.";
    return err.message;
  }
  function queryErrorText(err, stage) {
    if (err.status === 401) return "Your session has expired — reload the page.";
    if (err.status === 400 || err.status === 422) return "Rejected: " + (err.message || "invalid query.");
    if (err.status >= 500 && stage === "generation") {
      return "The LLM upstream (Gemini) is likely rate-limited or briefly unavailable. Wait a few seconds and try again.";
    }
    if (err.status >= 500) return "Server error during " + stage + ". Try again.";
    return err.message;
  }

  // ---------- account bar ----------

  function accountBar({ badgeLabel, badgeKind, actions }) {
    return el("div", { class: "account-bar" },
      el("span", { class: "session-badge " + badgeKind }, badgeLabel),
      el("div", { class: "account-actions" }, ...actions));
  }

  // ================= VIEWS =================

  // -- logged-out: auth panel (login / register) + "continue anonymously" --
  // anonDocs === null  → true logged-out (no session).
  // anonDocs is a number → arrived here from an anonymous session; used to warn that
  // those documents won't carry over, and to offer a way back.

  function renderLoggedOut(anonDocs = null) {
    const fromAnon = anonDocs !== null;
    let carryoverConfirmed = false;

    // guard a register/login submission with the carry-over confirm when coming from
    // an anonymous session that has documents. Fires at most once.
    async function guarded(action) {
      if (fromAnon && anonDocs > 0 && !carryoverConfirmed) {
        const ok = await confirmDialog({
          title: "Leave your anonymous documents behind?",
          message: `You have ${anonDocs} document${anonDocs === 1 ? "" : "s"} in this anonymous session. They belong to the anonymous session only and will NOT be carried over to your account — they are discarded by design. Continue?`,
          confirmLabel: "Continue",
        });
        if (!ok) return;
        carryoverConfirmed = true;
      }
      await action();
    }

    // login form
    const loginUser = el("input", { type: "text", required: true, autocomplete: "username", placeholder: "username" });
    const loginPass = el("input", { type: "password", required: true, autocomplete: "current-password", placeholder: "password" });
    const loginErr = el("p", { class: "status", role: "alert", "aria-live": "assertive" });
    const loginBtn = el("button", { class: "btn btn-primary", type: "submit" }, "Log in");
    const loginForm = el("form", {
      onsubmit: (e) => {
        e.preventDefault();
        guarded(async () => {
          loginBtn.disabled = true;
          setStatus(loginErr, "loading", "Signing in…");
          try {
            const username = loginUser.value;
            await API.login(username, loginPass.value);
            // Login guarantees a valid registered session — go straight to the app,
            // no whoami round-trip (which is where the "stuck on login" bounce came from).
            renderRegistered(username);
          } catch (err) {
            // Backend is deliberately non-distinguishing: unknown user and wrong
            // password both come back as 401 "Login unsuccessful." Do not leak more.
            setStatus(loginErr, "error", (err.status === 401 || err.status === 422) ? "Login unsuccessful — check your username and password." : (err.message || "Login failed."));
            loginBtn.disabled = false;
          }
        });
      },
    },
      el("label", null, "Username"), loginUser,
      el("label", null, "Password"), loginPass,
      loginBtn, loginErr);

    // register form
    const regUser = el("input", { type: "text", required: true, autocomplete: "username", placeholder: "username", maxlength: "64" });
    const regPass = el("input", { type: "password", required: true, autocomplete: "new-password", placeholder: "at least 8 characters", minlength: "8", maxlength: "128" });
    const regPass2 = el("input", { type: "password", required: true, autocomplete: "new-password", placeholder: "re-enter password", minlength: "8", maxlength: "128" });
    const regErr = el("p", { class: "status", role: "alert", "aria-live": "assertive" });
    const regBtn = el("button", { class: "btn btn-primary", type: "submit" }, "Create account");
    const regForm = el("form", {
      onsubmit: (e) => {
        e.preventDefault();
        guarded(async () => {
          if (regPass.value !== regPass2.value) {
            setStatus(regErr, "error", "Passwords don't match.");
            regPass2.focus();
            return;
          }
          regBtn.disabled = true;
          setStatus(regErr, "loading", "Creating account…");
          try {
            await API.register(regUser.value, regPass.value);
            // Register does NOT create a session; the user must now log in.
            switchTab("login");
            loginUser.value = regUser.value;
            loginPass.value = "";
            loginPass.focus();
            setStatus(loginErr, "success", "Account created — now log in.");
          } catch (err) {
            // Register genuinely distinguishes a taken username (409) — the backend
            // already exposes this, so matching it here leaks nothing new.
            if (err.status === 409) setStatus(regErr, "error", "That username is already taken.");
            else if (err.status === 422) setStatus(regErr, "error", "Password must be at least 8 characters.");
            else setStatus(regErr, "error", err.message || "Registration failed.");
          } finally {
            regBtn.disabled = false;
          }
        });
      },
    },
      el("label", null, "Username"), regUser,
      el("label", null, "Password"), regPass,
      el("label", null, "Confirm password"), regPass2,
      el("p", { class: "hint" }, "8–128 characters. There's no password reset yet, so keep it safe."),
      regBtn, regErr);

    // segmented tab toggle
    const tabLogin = el("button", { class: "seg-btn is-active", type: "button", onclick: () => switchTab("login") }, "Log in");
    const tabRegister = el("button", { class: "seg-btn", type: "button", onclick: () => switchTab("register") }, "Create account");
    function switchTab(which) {
      const login = which === "login";
      tabLogin.classList.toggle("is-active", login);
      tabRegister.classList.toggle("is-active", !login);
      loginForm.hidden = !login;
      regForm.hidden = login;
      (login ? loginUser : regUser).focus({ preventScroll: true });
    }
    regForm.hidden = true;

    const panelExtras = [];
    if (fromAnon) {
      panelExtras.push(
        el("button", { class: "linklike", type: "button", onclick: () => renderAnonymous() }, "← Back to your anonymous session")
      );
    } else {
      panelExtras.push(
        el("div", { class: "or-divider" }, "or"),
        el("button", {
          class: "btn btn-secondary btn-block",
          type: "button",
          onclick: async (e) => {
            e.target.disabled = true;
            try {
              await API.anonymousLogin();
              await boot();
            } catch (err) {
              e.target.disabled = false;
              toast(err.message || "Couldn't start an anonymous session.", "error");
            }
          },
        }, "Continue anonymously"),
        el("p", { class: "hint center" }, "No account needed — try it now. Anonymous documents live with the session and aren't saved to an account.")
      );
    }

    const view = el("div", { class: "auth-shell" },
      el("section", { class: "intro" },
        el("h1", null, "Groundwork"),
        el("p", { class: "tagline" }, "RAG from scratch, down to the auth layer."),
        el("p", { class: "lede" }, "Ask natural-language questions grounded in your own documents. Add text and Groundwork chunks it, embeds it locally, retrieves the most relevant passages, and has an LLM answer from them — so answers stay tied to your sources.")),
      el("div", { class: "card auth-panel" },
        el("div", { class: "seg" }, tabLogin, tabRegister),
        loginForm, regForm, ...panelExtras));

    mount(view);
  }

  // -- anonymous: the working app + a "keep your work" nudge --

  function renderAnonymous() {
    const { node, refreshDocs } = buildWorkspace();

    const bar = accountBar({
      badgeLabel: "Anonymous session",
      badgeKind: "badge-anon",
      actions: [
        el("button", { class: "btn btn-primary btn-sm", type: "button", onclick: enterAuthFromAnon }, "Create account / Log in"),
        el("button", {
          class: "btn btn-secondary btn-sm", type: "button",
          onclick: async () => {
            let count = 0;
            try { count = (await API.listDocuments()).length; } catch { /* fall through */ }
            if (count > 0) {
              const ok = await confirmDialog({
                title: "End this anonymous session?",
                message: `You have ${count} document${count === 1 ? "" : "s"} in this session. Ending it abandons them — anonymous data isn't recoverable. Continue?`,
                confirmLabel: "End session", danger: true,
              });
              if (!ok) return;
            }
            try { await API.logout(); } catch { /* ignore */ }
            await boot();
          },
        }, "End session"),
      ],
    });

    const banner = el("div", { class: "banner banner-info" },
      el("strong", null, "You're browsing anonymously. "),
      "Your documents live with this session only — they won't be carried to an account if you register. Create an account to keep your work.");

    mount(el("div", null, bar, banner, node));
    refreshDocs();
  }

  async function enterAuthFromAnon() {
    let count = 0;
    try { count = (await API.listDocuments()).length; } catch { /* treat as 0 */ }
    renderLoggedOut(count);
  }

  // -- registered: the working app + full account management --

  function renderRegistered(username) {
    const { node, refreshDocs } = buildWorkspace();

    const bar = accountBar({
      badgeLabel: username,
      badgeKind: "badge-user",
      actions: [
        el("button", {
          class: "btn btn-secondary btn-sm", type: "button",
          onclick: async () => { try { await API.logout(); } catch { /* ignore */ } await boot(); },
        }, "Log out"),
        el("button", {
          class: "btn btn-secondary btn-sm", type: "button",
          onclick: async () => {
            const ok = await confirmDialog({
              title: "Log out everywhere?",
              message: "This ends every active session for this account on all devices. You'll need to log in again.",
              confirmLabel: "Log out everywhere",
            });
            if (!ok) return;
            try { await API.logoutEverywhere(); } catch (err) { toast(err.message || "Failed.", "error"); return; }
            await boot();
          },
        }, "Log out everywhere"),
        el("button", {
          class: "btn btn-danger btn-sm", type: "button",
          onclick: async () => {
            const ok = await confirmDialog({
              title: "Delete your account?",
              message: "This permanently deletes your account and ALL of its documents, chunks and vectors. This cannot be undone.",
              confirmLabel: "Delete my account", danger: true, requireText: "DELETE",
            });
            if (!ok) return;
            try { await API.deleteAccount(); } catch (err) {
              toast(err.status === 401 ? "Your session has expired — reload the page." : (err.message || "Failed."), "error");
              return;
            }
            await boot();
          },
        }, "Delete account"),
      ],
    });

    mount(el("div", null, bar, node));
    refreshDocs();
  }

  // -- iframe block: cookies (SameSite=Lax) aren't sent inside a cross-origin frame --

  function renderIframeWarning() {
    mount(el("div", { class: "iframe-warning" },
      el("div", { class: "card" },
        el("h1", null, "Open Groundwork directly"),
        el("p", null, "Groundwork is running inside an embedded frame. Its session cookie is SameSite=Lax and isn't sent inside a cross-origin frame, so login and the demo can't work here."),
        el("p", null, "Open it at its own URL to use it."),
        // real link, not a JS top-navigation: the embedding iframe (e.g. HF Spaces)
        // is sandboxed without allow-top-navigation, so assigning window.top.location
        // throws SecurityError. A new tab only needs allow-popups, which embeds grant.
        el("a", {
          class: "btn btn-primary",
          href: "https://haberric-groundwork.hf.space/",
          target: "_blank", rel: "noopener",
        }, "Open Groundwork directly"))));
  }

  function renderFatal(err) {
    mount(el("div", { class: "auth-shell" },
      el("div", { class: "card" },
        el("h1", null, "Can't reach Groundwork"),
        el("p", null, err && err.message ? err.message : "The server didn't respond."),
        el("button", { class: "btn btn-primary", type: "button", onclick: () => boot() }, "Retry"))));
  }

  // ================= BOOT =================

  async function boot() {
    if (window.self !== window.top) {
      renderIframeWarning();
      return;
    }
    let me;
    try {
      me = await API.whoami();
    } catch (err) {
      if (err.status === 401) { renderLoggedOut(); return; }
      renderFatal(err);
      return;
    }
    if (me.authenticated) renderRegistered(me.username);
    else renderAnonymous();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
