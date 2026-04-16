/**
 * Dory Memory — perplexity.ai content script
 */
(function () {
  const INPUT_SELECTOR = "textarea[placeholder]";
  const RESPONSE_SELECTOR = ".prose";

  let lastUserTurn = "";

  function getInputText() {
    const el = document.querySelector(INPUT_SELECTOR);
    return el ? el.value.trim() : "";
  }

  function watchResponses(callback) {
    new MutationObserver(() => {
      const turns = document.querySelectorAll(RESPONSE_SELECTOR);
      if (!turns.length) return;
      const last = turns[turns.length - 1];
      const text = last.innerText.trim();
      if (text && lastUserTurn && text !== window.__doryLastResponse) {
        window.__doryLastResponse = text;
        callback({ userTurn: lastUserTurn, assistantTurn: text });
      }
    }).observe(document.body, { childList: true, subtree: true });

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
    sessionId: `perplexity-${Date.now()}`,
  });
})();
