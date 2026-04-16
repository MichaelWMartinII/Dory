/**
 * Dory Memory — claude.ai content script
 */
(function () {
  const INPUT_SELECTOR = 'div[contenteditable="true"][data-placeholder]';
  const RESPONSE_SELECTOR = '[data-testid="assistant-message"]';

  let lastUserTurn = "";
  let responseObserver = null;
  let responseCallback = null;

  function getInputText() {
    const el = document.querySelector(INPUT_SELECTOR);
    return el ? el.innerText.trim() : "";
  }

  function watchResponses(callback) {
    responseCallback = callback;
    const container = document.querySelector("main") || document.body;
    responseObserver = new MutationObserver(() => {
      const turns = document.querySelectorAll(RESPONSE_SELECTOR);
      if (turns.length === 0) return;
      const last = turns[turns.length - 1];
      const text = last.innerText.trim();
      if (text && lastUserTurn && text !== window.__doryLastResponse) {
        window.__doryLastResponse = text;
        callback({ userTurn: lastUserTurn, assistantTurn: text });
      }
    });
    responseObserver.observe(container, { childList: true, subtree: true });

    // Capture user turn on submit
    document.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        const t = getInputText();
        if (t) lastUserTurn = t;
      }
    }, true);
  }

  window.DoryBase.init({
    getInputText,
    onResponse: watchResponses,
    sessionId: `claude-${location.pathname.split("/").filter(Boolean).pop() || "new"}`,
  });
})();
