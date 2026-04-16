/**
 * Dory Memory — Background Service Worker
 *
 * Handles all API calls to the local Dory REST server.
 * Content scripts send messages here; we make the fetch() calls
 * (content scripts can't hit localhost directly in some configurations).
 */

const DEFAULT_PORT = 7341;

async function getServerUrl() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ serverPort: DEFAULT_PORT }, (items) => {
      resolve(`http://127.0.0.1:${items.serverPort}`);
    });
  });
}

async function doryFetch(path, options = {}) {
  const base = await getServerUrl();
  try {
    const resp = await fetch(`${base}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    if (!resp.ok) {
      const text = await resp.text();
      return { error: `HTTP ${resp.status}: ${text}` };
    }
    return await resp.json();
  } catch (e) {
    return { error: "offline", message: e.message };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case "DORY_HEALTH":
      doryFetch("/health").then(sendResponse);
      return true;

    case "DORY_QUERY":
      doryFetch(`/query?topic=${encodeURIComponent(msg.topic)}&reference_date=${msg.referenceDate || ""}`)
        .then(sendResponse);
      return true;

    case "DORY_OBSERVE":
      doryFetch("/observe", {
        method: "POST",
        body: JSON.stringify({ content: msg.content, node_type: msg.nodeType || "CONCEPT" }),
      }).then(sendResponse);
      return true;

    case "DORY_INGEST":
      doryFetch("/ingest", {
        method: "POST",
        body: JSON.stringify({
          user_turn: msg.userTurn,
          assistant_turn: msg.assistantTurn,
          session_id: msg.sessionId || "",
        }),
      }).then(sendResponse);
      return true;

    case "DORY_STATS":
      doryFetch("/stats").then(sendResponse);
      return true;

    default:
      sendResponse({ error: "unknown message type" });
  }
});

// Keyboard shortcut → toggle panel
chrome.commands.onCommand.addListener((command) => {
  if (command === "toggle-dory") {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { type: "DORY_TOGGLE" });
      }
    });
  }
});
