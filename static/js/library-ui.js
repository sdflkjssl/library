(() => {
  const searchModal = document.querySelector("[data-search-modal]");
  const searchInput = document.querySelector("[data-search-input]");
  const searchResults = document.querySelector("[data-search-results]");
  const searchTitle = document.getElementById("search-modal-title");
  let activePicker = null;
  let searchTimer = null;

  function setHidden(element, hidden) {
    if (element) {
      element.hidden = hidden;
    }
  }

  function textNode(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    element.textContent = text;
    return element;
  }

  function pickerTargetInput() {
    if (!activePicker) {
      return null;
    }
    return document.getElementById(activePicker.dataset.targetInput);
  }

  function selectedDisplay() {
    if (!activePicker) {
      return null;
    }
    return activePicker.querySelector("[data-picker-selected]");
  }

  function closeSearch() {
    setHidden(searchModal, true);
    activePicker = null;
    if (searchInput) {
      searchInput.value = "";
    }
  }

  function renderSearchState(message) {
    searchResults.replaceChildren(textNode("p", "empty-state", message));
  }

  function renderResults(items) {
    searchResults.replaceChildren();
    if (!items.length) {
      renderSearchState("No matches found.");
      return;
    }

    for (const item of items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-result";
      button.dataset.itemId = item.id;

      const content = document.createElement("span");
      content.className = "search-result-main";
      content.append(
        textNode("strong", null, item.title),
        textNode("span", null, [item.subtitle, item.meta].filter(Boolean).join(" - ")),
      );
      button.append(content);

      if (item.availability) {
        button.append(textNode("span", `badge ${item.availabilityClass || "neutral"}`, item.availability));
      }

      button.addEventListener("click", () => {
        const target = pickerTargetInput();
        const display = selectedDisplay();
        if (!target || !display) {
          return;
        }
        target.value = item.id;
        display.replaceChildren(
          textNode("strong", null, item.title),
          textNode("span", null, [item.subtitle, item.meta].filter(Boolean).join(" - ")),
        );
        closeSearch();
      });

      searchResults.append(button);
    }
  }

  async function runSearch() {
    if (!activePicker) {
      return;
    }
    const endpoint = activePicker.dataset.endpoint;
    const query = searchInput.value.trim();
    const url = new URL(endpoint, window.location.origin);
    if (query) {
      url.searchParams.set("q", query);
    }

    renderSearchState("Searching...");
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error("Search failed");
      }
      const payload = await response.json();
      renderResults(payload.items || []);
    } catch (error) {
      renderSearchState("Search is unavailable. Please try again.");
    }
  }

  function openSearch(picker) {
    activePicker = picker;
    searchTitle.textContent = picker.dataset.title || "Search";
    searchInput.placeholder = picker.dataset.placeholder || "Search";
    setHidden(searchModal, false);
    searchInput.value = "";
    searchInput.focus();
    runSearch();
  }

  document.addEventListener("click", (event) => {
    const openButton = event.target.closest("[data-picker-open]");
    if (openButton) {
      openSearch(openButton.closest("[data-search-picker]"));
      return;
    }

    if (
      event.target.matches("[data-search-close]")
      || event.target === searchModal
    ) {
      closeSearch();
    }
  });

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(runSearch, 180);
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && searchModal && !searchModal.hidden) {
      closeSearch();
    }
  });

  const confirmModal = document.querySelector("[data-confirm-modal]");
  const confirmTitle = document.getElementById("confirm-modal-title");
  const confirmBody = document.querySelector("p[data-confirm-body]");
  const confirmSubmit = document.querySelector("[data-confirm-submit]");
  let pendingForm = null;

  function closeConfirm() {
    setHidden(confirmModal, true);
    pendingForm = null;
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-confirm-return]");
    if (!form || form.dataset.confirmed === "true") {
      return;
    }
    event.preventDefault();
    pendingForm = form;
    confirmTitle.textContent = form.dataset.confirmTitle || "Confirm action";
    confirmBody.textContent = form.dataset.confirmMessage || "Are you sure?";
    setHidden(confirmModal, false);
  });

  document.addEventListener("click", (event) => {
    if (
      event.target.matches("[data-confirm-cancel]")
      || event.target === confirmModal
    ) {
      closeConfirm();
    }
  });

  if (confirmSubmit) {
    confirmSubmit.addEventListener("click", () => {
      if (!pendingForm) {
        return;
      }
      pendingForm.dataset.confirmed = "true";
      pendingForm.submit();
    });
  }
})();
