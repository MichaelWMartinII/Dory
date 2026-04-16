/**
 * Dory Memory — Base Content Script
 *
 * Injects the sidebar panel and provides shared utilities.
 * Site-specific scripts (claude.js, chatgpt.js, etc.) call
 * window.DoryBase.init() with site-specific selectors.
 */

(function () {
  if (window.__doryLoaded) return;
  window.__doryLoaded = true;

  // ------------------------------------------------------------------
  // Sidebar DOM
  // ------------------------------------------------------------------

  let panel = null;
  let visible = false;

  function createPanel() {
    panel = document.createElement("div");
    panel.id = "dory-panel";
    panel.innerHTML = `
      <div id="dory-header">
        <span id="dory-title">🐟 Dory</span>
        <div id="dory-header-actions">
          <button id="dory-refresh" title="Refresh memories">↻</button>
          <button id="dory-collapse" title="Collapse">×</button>
        </div>
      </div>
      <div id="dory-status"></div>
      <div id="dory-context"></div>
      <div id="dory-observe-section">
        <textarea id="dory-observe-input" placeholder="Observe a memory…" rows="2"></textarea>
        <div id="dory-observe-controls">
          <select id="dory-observe-type">
            <option value="CONCEPT">CONCEPT</option>
            <option value="PREFERENCE">PREFERENCE</option>
            <option value="EVENT">EVENT</option>
            <option value="ENTITY">ENTITY</option>
            <option value="BELIEF">BELIEF</option>
          </select>
          <button id="dory-observe-btn">Store</button>
        </div>
      </div>
    `;
    document.body.appendChild(panel);

    document.getElementById("dory-collapse").addEventListener("click", hidePanel);
    document.getElementById("dory-refresh").addEventListener("click", () => queryDory(""));
    document.getElementById("dory-observe-btn").addEventListener("click", observeMemory);
  }

  function showPanel() {
    if (!panel) createPanel();
    panel.classList.add("dory-visible");
    visible = true;
    checkServer();
  }

  function hidePanel() {
    if (panel) panel.classList.remove("dory-visible");
    visible = false;
  }

  function togglePanel() {
    if (visible) hidePanel(); else showPanel();
  }

  // ------------------------------------------------------------------
  // Server comms
  // ------------------------------------------------------------------

  function msg(type, payload) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type, ...payload }, (resp) => resolve(resp || {}));
    });
  }

  async function checkServer() {
    setStatus("Connecting…");
    const r = await msg("DORY_HEALTH");
    if (r.error) {
      setStatus("⚠ Dory offline — run: dory serve", "error");
    } else {
      setStatus(`v${r.version} · ${r.node_count ?? "?"} nodes`, "ok");
      queryDory("");
    }
  }

  async function queryDory(topic) {
    setStatus("Loading memories…");
    const r = await msg("DORY_QUERY", { topic: topic || document.title });
    if (r.error) {
      setStatus("⚠ Dory offline — run: dory serve", "error");
      return;
    }
    setStatus(`${r.node_count} active nodes`, "ok");
    renderContext(r.context);
  }

  async function observeMemory() {
    const content = document.getElementById("dory-observe-input").value.trim();
    if (!content) return;
    const nodeType = document.getElementById("dory-observe-type").value;
    setStatus("Storing…");
    const r = await msg("DORY_OBSERVE", { content, nodeType });
    if (r.error) {
      setStatus("⚠ Store failed", "error");
    } else {
      setStatus(`Stored: ${r.id}`, "ok");
      document.getElementById("dory-observe-input").value = "";
    }
  }

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  function setStatus(text, cls = "") {
    const el = document.getElementById("dory-status");
    if (!el) return;
    el.textContent = text;
    el.className = cls ? `dory-status-${cls}` : "";
  }

  function renderContext(context) {
    const el = document.getElementById("dory-context");
    if (!el) return;
    if (!context || context.startsWith("(no relevant")) {
      el.innerHTML = '<p class="dory-empty">No memories found for this topic.</p>';
      return;
    }
    // Render markdown-ish sections as simple HTML
    el.innerHTML = context
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/^- (.+)$/gm, '<p class="dory-node">$1</p>')
      .replace(/\n{2,}/g, "\n");
  }

  // ------------------------------------------------------------------
  // Auto-extraction
  // ------------------------------------------------------------------

  window.DoryBase = {
    init({ getInputText, onResponse, sessionId }) {
      // Show panel on load
      showPanel();

      // Auto-extract: hook response observer from site script
      if (onResponse) {
        onResponse(({ userTurn, assistantTurn }) => {
          msg("DORY_INGEST", { userTurn, assistantTurn, sessionId: sessionId || "" });
          // Re-query after extraction (small delay for server to process)
          setTimeout(() => queryDory(userTurn.slice(0, 100)), 3000);
        });
      }
    },
    query: queryDory,
    toggle: togglePanel,
  };

  // Listen for toggle from keyboard shortcut
  chrome.runtime.onMessage.addListener((m) => {
    if (m.type === "DORY_TOGGLE") togglePanel();
  });
})();
