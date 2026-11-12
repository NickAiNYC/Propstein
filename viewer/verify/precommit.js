function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

const KEYS = ["book", "kickoff_at", "line", "market", "odds", "player_id", "side", "slate"];

function readPayload() {
  const payload = {
    book: document.getElementById("book").value.trim(),
    kickoff_at: document.getElementById("kickoff_at").value.trim(),
    line: Number(document.getElementById("line").value),
    market: document.getElementById("market").value.trim(),
    odds: Number(document.getElementById("odds").value),
    player_id: document.getElementById("player_id").value.trim(),
    side: document.getElementById("side").value.trim(),
    slate: document.getElementById("slate").value.trim()
  };
  if (KEYS.some((key) => payload[key] === "" || payload[key] === null)) return null;
  if (!Number.isFinite(payload.line) || !Number.isFinite(payload.odds)) return null;
  return payload;
}

async function hashPayload() {
  const out = document.getElementById("hashOut");
  const payload = readPayload();
  if (!payload) {
    out.textContent = "Fill every field. line and odds must be numbers.";
    return;
  }
  const digest = await sha256Hex(canonicalJson(payload));
  if (!/^[0-9a-f]{64}$/.test(digest)) {
    out.textContent = "reject: hash was not 64 hex";
    return;
  }
  out.textContent = digest;
}

function renderRows(logRows, status) {
  const body = document.getElementById("rows");
  const tape = Boolean(status && status.close_tape_present);
  const byHash = new Map((status && status.rows ? status.rows : []).map((row) => [row.payload_sha256, row]));
  if (!logRows.length) {
    body.innerHTML = "<tr><td colspan=\"3\">No commits.</td></tr>";
    return;
  }
  body.innerHTML = logRows.map((row) => {
    const found = byHash.get(row.payload_sha256);
    let state = found && found.state ? found.state : "COMMITTED";
    if (!tape && state !== "COMMITTED" && state !== "AWAITING_CLOSE") state = "COMMITTED";
    const verified = tape && found && found.verified === true;
    const label = verified ? "verified" : state;
    return `<tr><td>${row.received_at}</td><td><code>${row.payload_sha256.slice(0, 12)}</code></td><td>${label}</td></tr>`;
  }).join("");
}

async function loadLog() {
  const logResponse = await fetch("/precommit_log.jsonl", { cache: "no-store" });
  const logText = logResponse.ok ? await logResponse.text() : "";
  const logRows = logText.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => JSON.parse(line));
  let status = null;
  const statusResponse = await fetch("/precommit_status.json", { cache: "no-store" });
  if (statusResponse.ok) status = await statusResponse.json();
  const note = document.getElementById("tapeNote");
  if (!status || status.close_tape_present !== true) {
    note.textContent = "No close tape with captured_at < kickoff_at. This page shows COMMITTED and AWAITING_CLOSE only.";
  } else {
    note.textContent = "Close tape is present. A row is verified only when the reveal script set verified true.";
  }
  renderRows(logRows, status);
}

document.getElementById("hashBtn").addEventListener("click", () => {
  hashPayload().catch(() => {
    document.getElementById("hashOut").textContent = "hash failed";
  });
});
loadLog().catch(() => {
  document.getElementById("rows").innerHTML = "<tr><td colspan=\"3\">Log unavailable.</td></tr>";
});
