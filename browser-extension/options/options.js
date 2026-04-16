document.addEventListener("DOMContentLoaded", () => {
  chrome.storage.sync.get(
    { serverPort: 7341, autoExtract: true, autoShow: true },
    (items) => {
      document.getElementById("serverPort").value = items.serverPort;
      document.getElementById("autoExtract").checked = items.autoExtract;
      document.getElementById("autoShow").checked = items.autoShow;
    }
  );

  document.getElementById("save").addEventListener("click", () => {
    const port = parseInt(document.getElementById("serverPort").value, 10);
    if (isNaN(port) || port < 1024 || port > 65535) {
      document.getElementById("status").textContent = "Invalid port number.";
      document.getElementById("status").style.color = "#ff6b6b";
      return;
    }
    chrome.storage.sync.set({
      serverPort: port,
      autoExtract: document.getElementById("autoExtract").checked,
      autoShow: document.getElementById("autoShow").checked,
    }, () => {
      const s = document.getElementById("status");
      s.textContent = "Saved!";
      s.style.color = "#6bcb77";
      setTimeout(() => { s.textContent = ""; }, 2000);
    });
  });
});
