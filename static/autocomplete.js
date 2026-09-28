/*
 * Business-name autocomplete: attaches a debounced as-you-type dropdown to
 * a "business name" text input, backed by /api/places. Picking a suggestion
 * also fills in the category and location fields, since a picked result is
 * a specific real place -- no need to retype what's already known about it.
 *
 * Degrades silently: if the lookup fails or is slow, the field just behaves
 * like a normal text input -- nothing here is required to submit the form.
 */
(function () {
  "use strict";

  function debounce(fn, wait) {
    var t = null;
    return function () {
      var args = arguments;
      clearTimeout(t);
      t = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }

  function attachPlaceAutocomplete(nameId, categoryId, locationId) {
    var nameInput = document.getElementById(nameId);
    if (!nameInput) return;
    var categoryInput = categoryId ? document.getElementById(categoryId) : null;
    var locationInput = locationId ? document.getElementById(locationId) : null;

    var wrap = document.createElement("div");
    wrap.className = "ac-wrap";
    nameInput.parentNode.insertBefore(wrap, nameInput);
    wrap.appendChild(nameInput);

    var listId = nameId + "-ac-list";
    var list = document.createElement("ul");
    list.className = "ac-list";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.appendChild(list);

    // ARIA combobox wiring so screen-reader users get the same "here are
    // suggestions" signal sighted users get from the dropdown appearing.
    nameInput.setAttribute("role", "combobox");
    nameInput.setAttribute("aria-autocomplete", "list");
    nameInput.setAttribute("aria-expanded", "false");
    nameInput.setAttribute("aria-controls", listId);
    nameInput.setAttribute("autocomplete", "off");

    var currentResults = [];
    var activeIndex = -1;
    var requestSeq = 0;

    function closeList() {
      list.hidden = true;
      list.innerHTML = "";
      currentResults = [];
      activeIndex = -1;
      nameInput.setAttribute("aria-expanded", "false");
      nameInput.removeAttribute("aria-activedescendant");
    }

    function selectResult(result) {
      nameInput.value = result.name || nameInput.value;
      if (categoryInput && result.category) categoryInput.value = result.category;
      if (locationInput && result.location) locationInput.value = result.location;
      closeList();
    }

    function renderResults(results) {
      currentResults = results;
      activeIndex = -1;
      list.innerHTML = "";
      if (!results.length) {
        closeList();
        return;
      }
      results.forEach(function (r, i) {
        var li = document.createElement("li");
        li.className = "ac-item";
        li.id = listId + "-" + i;
        li.setAttribute("role", "option");
        var main = document.createElement("div");
        main.className = "ac-item-name";
        main.textContent = r.name;
        li.appendChild(main);
        if (r.full_address) {
          var sub = document.createElement("div");
          sub.className = "ac-item-sub";
          sub.textContent = r.full_address;
          li.appendChild(sub);
        }
        li.addEventListener("mousedown", function (e) {
          e.preventDefault(); // fire before the input's blur closes the list
          selectResult(r);
        });
        li.addEventListener("mouseenter", function () { setActive(i); });
        list.appendChild(li);
      });
      list.hidden = false;
      nameInput.setAttribute("aria-expanded", "true");
    }

    function setActive(index) {
      var items = list.querySelectorAll(".ac-item");
      items.forEach(function (el) { el.classList.remove("ac-item-active"); el.setAttribute("aria-selected", "false"); });
      if (index >= 0 && index < items.length) {
        items[index].classList.add("ac-item-active");
        items[index].setAttribute("aria-selected", "true");
        nameInput.setAttribute("aria-activedescendant", items[index].id);
        activeIndex = index;
      }
    }

    var runSearch = debounce(function (query) {
      var seq = ++requestSeq;
      fetch("/api/places?q=" + encodeURIComponent(query))
        .then(function (resp) { return resp.ok ? resp.json() : { results: [] }; })
        .then(function (data) {
          if (seq !== requestSeq) return; // a newer keystroke already superseded this
          renderResults((data && data.results) || []);
        })
        .catch(function () { /* silent -- typing still works as a plain field */ });
    }, 300);

    nameInput.addEventListener("input", function () {
      var q = nameInput.value.trim();
      if (q.length < 3) {
        closeList();
        return;
      }
      runSearch(q);
    });

    nameInput.addEventListener("keydown", function (e) {
      if (list.hidden) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive(Math.min(activeIndex + 1, currentResults.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive(Math.max(activeIndex - 1, 0));
      } else if (e.key === "Enter") {
        if (activeIndex >= 0 && currentResults[activeIndex]) {
          e.preventDefault();
          selectResult(currentResults[activeIndex]);
        }
      } else if (e.key === "Escape") {
        closeList();
      }
    });

    nameInput.addEventListener("blur", function () {
      setTimeout(closeList, 100); // allow a pending mousedown selection to land first
    });
  }

  window.attachPlaceAutocomplete = attachPlaceAutocomplete;

  // Auto-init from data attributes instead of a per-page inline <script>
  // block -- keeps every page's Content-Security-Policy free of
  // 'unsafe-inline' for scripts. Add data-autocomplete-name to the name
  // field, with data-autocomplete-category / data-autocomplete-location
  // pointing at the ids of the fields to auto-fill.
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-autocomplete-name]").forEach(function (input) {
      attachPlaceAutocomplete(
        input.id,
        input.getAttribute("data-autocomplete-category") || null,
        input.getAttribute("data-autocomplete-location") || null
      );
    });
  });
})();
