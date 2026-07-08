// Demo page logic: ingest → /ingest/store, question → /query/retrieve + /query/generate.
// All URLs are relative so this works same-origin anywhere (local, Docker, HF Spaces).

// Generation can legitimately take a while (backend LLM timeout is 60 s), so the
// client aborts a bit above that instead of hanging forever.
const REQUEST_TIMEOUT_MS = 90_000;

// Error carrying the HTTP status plus the server's {"detail": ...} message, so
// handlers can show specific text per status code.
class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed with status ${status}`);
    this.status = status;
  }
}

async function postJSON(url, body) {
  let resp;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (err) {
    if (err.name === "TimeoutError") {
      throw new ApiError(0, "The request timed out — the server may be busy. Try again.");
    }
    throw new ApiError(0, "Can't reach the API — is the server running?");
  }
  if (!resp.ok) {
    let detail = "";
    try {
      const data = await resp.json();
      // FastAPI errors are {"detail": string} for HTTPException-style errors, or
      // {"detail": [ {...,"msg": ...} ]} for 422 validation errors.
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg).join("; ");
    } catch {
      // non-JSON error body (e.g. a bare 500) — fall through with empty detail
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json();
}

function setStatus(el, kind, text) {
  el.className = "status" + (kind ? " " + kind : "");
  if (kind === "loading") {
    // spinner is decorative markup, so it's the one place innerHTML is used
    el.innerHTML = '<span class="spinner" aria-hidden="true"></span>' + text;
  } else {
    el.textContent = text;
  }
}

// ---------- ingest ----------

const ingestForm = document.getElementById("ingest-form");
const ingestBtn = document.getElementById("ingest-btn");
const ingestStatus = document.getElementById("ingest-status");

ingestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  ingestBtn.disabled = true;
  setStatus(ingestStatus, "loading", "Chunking and embedding…");
  try {
    const docId = await postJSON("/ingest/store", {
      content: document.getElementById("ingest-content").value,
      filename: document.getElementById("ingest-filename").value,
      metadata: {},
    });
    setStatus(ingestStatus, "success", "Stored. Document id: ");
    const span = document.createElement("span");
    span.className = "doc-id";
    span.textContent = docId;
    ingestStatus.appendChild(span);
  } catch (err) {
    setStatus(ingestStatus, "error", ingestErrorText(err));
  } finally {
    ingestBtn.disabled = false;
  }
});

function ingestErrorText(err) {
  if (err.status === 400 || err.status === 422) {
    return "Rejected: " + (err.message || "invalid input.");
  }
  if (err.status >= 500) return "Server error while ingesting. Try again.";
  return err.message;
}

// ---------- query ----------

const queryForm = document.getElementById("query-form");
const queryBtn = document.getElementById("query-btn");
const chunksStatus = document.getElementById("chunks-status");
const chunkList = document.getElementById("chunk-list");
const answerStatus = document.getElementById("answer-status");
const answerBody = document.getElementById("answer-body");

queryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = document.getElementById("query-input").value;
  queryBtn.disabled = true;
  chunkList.replaceChildren();
  answerBody.textContent = "";
  setStatus(chunksStatus, "loading", "Searching vectors…");
  setStatus(answerStatus, "loading", "Retrieving + generating (the LLM can take a while)…");

  // Both requests run concurrently; each panel resolves on its own, so the
  // retrieved chunks usually appear well before the LLM answer.
  await Promise.allSettled([showChunks(query), showAnswer(query)]);
  queryBtn.disabled = false;
});

async function showChunks(query) {
  try {
    const chunks = await postJSON("/query/retrieve", { query });
    if (chunks.length === 0) {
      setStatus(chunksStatus, "error",
        "No chunks passed the similarity threshold — ingest something related to the question first.");
      return;
    }
    setStatus(chunksStatus, "", "");
    chunks.forEach((text, i) => {
      const li = document.createElement("li");
      const rank = document.createElement("span");
      rank.className = "chunk-rank";
      rank.textContent = "#" + (i + 1);
      li.append(rank, document.createTextNode(text));
      chunkList.appendChild(li);
    });
  } catch (err) {
    setStatus(chunksStatus, "error", queryErrorText(err, "retrieval"));
  }
}

async function showAnswer(query) {
  try {
    const answer = await postJSON("/query/generate", { query });
    setStatus(answerStatus, "", "");
    answerBody.textContent = answer;
  } catch (err) {
    setStatus(answerStatus, "error", queryErrorText(err, "generation"));
  }
}

function queryErrorText(err, stage) {
  if (err.status === 400 || err.status === 422) {
    return "Rejected: " + (err.message || "invalid query.");
  }
  if (err.status >= 500 && stage === "generation") {
    // The backend surfaces upstream Gemini failures (rate limits, overload) as 500.
    return "The LLM upstream (Gemini) is likely rate-limited or briefly unavailable. " +
      "Wait a few seconds and try again.";
  }
  if (err.status >= 500) return "Server error during " + stage + ". Try again.";
  return err.message;
}
