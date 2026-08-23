const recovery = window.__MONEY_MAP_SAFE_ERROR__;
const status = document.querySelector("#status");
const retry = document.querySelector("#retry");

retry?.addEventListener("click", async () => {
  retry.disabled = true;
  status.textContent = "Checking the private local service…";
  try {
    await recovery.restart();
    status.textContent = "Money Map is ready.";
  } catch {
    status.textContent = "The private local service is still unavailable.";
    retry.disabled = false;
  }
});

document.querySelector("#about")?.addEventListener("click", async () => {
  const about = await recovery.about();
  status.textContent = `Money Map ${about.runtime_version}`;
});
