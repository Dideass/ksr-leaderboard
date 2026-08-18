(() => {
  const body = document.querySelector("#ranking-body");
  const rows = [...document.querySelectorAll(".model-row")];
  const search = document.querySelector("#model-search");
  const provider = document.querySelector("#provider-filter");
  const confidence = document.querySelector("#confidence-filter");
  const sort = document.querySelector("#sort-control");
  const empty = document.querySelector("#empty-state");
  const more = document.querySelector("#view-more");
  const moreWrap = document.querySelector(".table-more");
  const modelDialog = document.querySelector("#model-dialog");
  const updatesDialog = document.querySelector("#updates-dialog");
  const dialogContent = document.querySelector("#dialog-content");

  const PAGE_LIMITS = [20, 50, 100, Infinity];
  let pageIndex = 0;

  const number = (row, key) => Number(row.dataset[key] || 0);

  function applyTableState() {
    if (!body) return;
    const query = search ? search.value.trim().toLocaleLowerCase("en") : "";
    const providerValue = provider ? provider.value : "";
    const confidenceValue = confidence ? confidence.value : "";
    const sortValue = sort ? sort.value : "rank";

    const ordered = [...rows].sort((first, second) => {
      if (sortValue === "coverage") {
        return number(second, "coverage") - number(first, "coverage") ||
          number(first, "rank") - number(second, "rank");
      }
      if (sortValue === "date") {
        return second.dataset.date.localeCompare(first.dataset.date) ||
          number(first, "rank") - number(second, "rank");
      }
      if (sortValue === "name") {
        return first.dataset.name.localeCompare(second.dataset.name, "en");
      }
      return number(first, "rank") - number(second, "rank") ||
        number(second, "coverage") - number(first, "coverage");
    });
    ordered.forEach((row) => body.append(row));

    const matched = ordered.filter((row) =>
      (!query || row.dataset.search.includes(query)) &&
      (!providerValue || row.dataset.provider === providerValue) &&
      (!confidenceValue || row.dataset.confidence === confidenceValue)
    );
    const unmatched = ordered.filter((row) => !matched.includes(row));
    unmatched.forEach((row) => {
      row.hidden = true;
    });

    const limit = PAGE_LIMITS[pageIndex];
    matched.forEach((row, index) => {
      row.hidden = index >= limit;
    });

    if (empty) empty.hidden = matched.length > 0;
    const shown = Math.min(limit, matched.length);
    const hasMore = shown < matched.length;
    if (moreWrap) moreWrap.hidden = !hasMore;
    if (more) {
      more.hidden = !hasMore;
      more.textContent = "Show More";
    }
  }

  function resetPaging() {
    pageIndex = 0;
    applyTableState();
  }

  function openModel(index) {
    const template = document.querySelector(`[data-model-template="${index}"]`);
    if (!template || !modelDialog) return;
    dialogContent.replaceChildren(template.content.cloneNode(true));
    modelDialog.showModal();
  }

  [search, provider, confidence].forEach((control) => {
    if (!control) return;
    control.addEventListener(control === search ? "input" : "change", resetPaging);
  });
  if (sort) sort.addEventListener("change", applyTableState);

  if (more) {
    more.addEventListener("click", () => {
      pageIndex = Math.min(pageIndex + 1, PAGE_LIMITS.length - 1);
      applyTableState();
    });
  }

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-open-model]");
    if (opener) openModel(opener.dataset.openModel);
    if (event.target.closest("[data-open-updates]") && updatesDialog) {
      updatesDialog.showModal();
    }
    if (event.target.matches("[data-close-dialog]")) {
      const dialog = event.target.closest("dialog");
      if (dialog) dialog.close();
    }
  });
  [modelDialog, updatesDialog].forEach((dialog) => {
    if (!dialog) return;
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  applyTableState();

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduceMotion) {
    document.querySelectorAll("[data-count]").forEach((el) => {
      const target = Number(el.dataset.count);
      if (!Number.isFinite(target)) return;
      const started = performance.now();
      const duration = 1100;
      const tick = (now) => {
        const t = Math.min(1, (now - started) / duration);
        el.textContent = String(Math.round(target * (1 - (1 - t) ** 3)));
        if (t < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });
  }
})();
