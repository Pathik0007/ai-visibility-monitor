/*
 * Business-name autocomplete.
 *
 * Two modes, both backed by /api/places:
 *   - single mode ("business name" fields): picking a suggestion replaces
 *     the whole field and can also fill in paired category/location fields.
 *   - multi mode ("competitors" field): the field holds a comma-separated
 *     list, so autocomplete only ever searches/replaces the segment
 *     currently being typed (after the last comma), leaving earlier entries
 *     alone, and never touches category/location.
 *
 * Location bias: when a name field is paired with a Location field, that
 * field's text is geocoded (via /api/geocode, debounced) into a lat/lon and
 * passed along with every /api/places call for that name field, so results
 * are ranked toward where the user actually typed rather than purely on
 * text-match fuzziness with no geography at all -- without this, a query
 * like "nene chicken" can rank a branch on the other side of the world
 * above the one actually near the user. The same bias is shared with a
 * paired competitors field so both widgets favor the same area.
 *
 * Degrades silently throughout: any failed/slow lookup just leaves the
 * field behaving like plain text -- nothing here is required to submit the
 * form.
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

  // One geocode-bias tracker per Location field, shared by every widget
  // paired with it (business name + competitors), so typing in Location
  // only triggers one /api/geocode call chain, not one per paired widget.
  var biasByLocationEl = new WeakMap();

  function getLocationBias(locationInput) {
    if (!locationInput) return { lat: null, lon: null };
    if (biasByLocationEl.has(locationInput)) return biasByLocationEl.get(locationInput);

    var state = { lat: null, lon: null };
    var runGeocode = debounce(function (text) {
      text = text.trim();
      if (text.length < 3) { state.lat = null; state.lon = null; return; }
      fetch("/api/geocode?q=" + encodeURIComponent(text))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (data && data.lat != null && data.lon != null) {
            state.lat = data.lat;
            state.lon = data.lon;
          }
        })
        .catch(function () { /* silent -- search just stays unbiased */ });
    }, 400);

    locationInput.addEventListener("input", function () { runGeocode(locationInput.value); });
    if (locationInput.value) runGeocode(locationInput.value);

    biasByLocationEl.set(locationInput, state);
    return state;
  }

  function placesUrl(query, bias) {
    var url = "/api/places?q=" + encodeURIComponent(query);
    if (bias && bias.lat != null && bias.lon != null) {
      url += "&lat=" + encodeURIComponent(bias.lat) + "&lon=" + encodeURIComponent(bias.lon);
    }
    return url;
  }

  // Builds the wrapper + dropdown DOM and the shared open/close/navigate
  // behavior used by both modes; `onSelect(result)` gets called with the
  // chosen suggestion.
  function buildWidget(input, onSelect) {
    var wrap = document.createElement("div");
    wrap.className = "ac-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    var listId = (input.id || "ac") + "-ac-list";
    var list = document.createElement("ul");
    list.className = "ac-list";
    list.id = listId;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    wrap.appendChild(list);

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", listId);
    input.setAttribute("autocomplete", "off");

    var currentResults = [];
    var activeIndex = -1;

    function close() {
      list.hidden = true;
      list.innerHTML = "";
      currentResults = [];
      activeIndex = -1;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    // `searched: true` means a request actually completed with zero matches
    // (as opposed to "hasn't searched yet") -- shown as a plain, unselectable
    // note rather than just closing the list, so a real "not in our
    // database" answer doesn't look identical to "nothing happened."
    function render(results, opts) {
      currentResults = results;
      activeIndex = -1;
      list.innerHTML = "";
      if (!results.length) {
        if (opts && opts.searched) {
          var empty = document.createElement("li");
          empty.className = "ac-empty";
          empty.setAttribute("role", "presentation");
          empty.textContent = "No matches -- you can still type it in manually.";
          list.appendChild(empty);
          list.hidden = false;
          input.setAttribute("aria-expanded", "true");
        } else {
          close();
        }
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
          onSelect(r);
          close();
        });
        li.addEventListener("mouseenter", function () { setActive(i); });
        list.appendChild(li);
      });
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    function setActive(index) {
      var items = list.querySelectorAll(".ac-item");
      items.forEach(function (el) { el.classList.remove("ac-item-active"); el.setAttribute("aria-selected", "false"); });
      if (index >= 0 && index < items.length) {
        items[index].classList.add("ac-item-active");
        items[index].setAttribute("aria-selected", "true");
        input.setAttribute("aria-activedescendant", items[index].id);
        activeIndex = index;
      }
    }

    input.addEventListener("keydown", function (e) {
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
          onSelect(currentResults[activeIndex]);
          close();
        }
      } else if (e.key === "Escape") {
        close();
      }
    });

    input.addEventListener("blur", function () {
      setTimeout(close, 100); // allow a pending mousedown selection to land first
    });

    return { render: render, close: close };
  }

  function attachPlaceAutocomplete(nameId, categoryId, locationId) {
    var nameInput = document.getElementById(nameId);
    if (!nameInput) return;
    var categoryInput = categoryId ? document.getElementById(categoryId) : null;
    var locationInput = locationId ? document.getElementById(locationId) : null;
    var bias = getLocationBias(locationInput);

    var widget = buildWidget(nameInput, function (result) {
      nameInput.value = result.name || nameInput.value;
      if (categoryInput && result.category) categoryInput.value = result.category;
      if (locationInput && result.location) locationInput.value = result.location;
    });

    // Guards against a slow earlier response landing after a faster later
    // one and overwriting it with stale results -- only the most recently
    // *fired* request is allowed to render.
    var requestSeq = 0;
    var runSearch = debounce(function (query) {
      var seq = ++requestSeq;
      fetch(placesUrl(query, bias))
        .then(function (resp) { return resp.ok ? resp.json() : { results: [] }; })
        .then(function (data) {
          if (seq !== requestSeq) return; // a newer search has since started
          widget.render((data && data.results) || [], { searched: true });
        })
        .catch(function () { /* silent -- typing still works as a plain field */ });
    }, 300);

    nameInput.addEventListener("input", function () {
      var q = nameInput.value.trim();
      if (q.length < 3) { requestSeq++; widget.close(); return; } // invalidate any in-flight response
      runSearch(q);
    });
  }

  // Multi-value mode for a comma-separated field (Competitors): searches
  // and replaces only the segment currently being typed after the last
  // comma, leaving everything before it untouched, and never fills in
  // category/location (a competitor is just a name here).
  function attachMultiValueAutocomplete(inputId, locationId) {
    var input = document.getElementById(inputId);
    if (!input) return;
    var locationInput = locationId ? document.getElementById(locationId) : null;
    var bias = getLocationBias(locationInput);

    function currentSegment() {
      var parts = input.value.split(",");
      return parts[parts.length - 1].trim();
    }

    var widget = buildWidget(input, function (result) {
      var parts = input.value.split(",");
      parts[parts.length - 1] = " " + (result.name || currentSegment());
      input.value = parts.join(",").replace(/^,\s*/, "").trim() + ", ";
      input.focus();
    });

    var requestSeq = 0;
    var runSearch = debounce(function (query) {
      var seq = ++requestSeq;
      fetch(placesUrl(query, bias))
        .then(function (resp) { return resp.ok ? resp.json() : { results: [] }; })
        .then(function (data) {
          if (seq !== requestSeq) return; // a newer search has since started
          widget.render((data && data.results) || [], { searched: true });
        })
        .catch(function () { /* silent -- typing still works as a plain field */ });
    }, 300);

    input.addEventListener("input", function () {
      var seg = currentSegment();
      if (seg.length < 3) { requestSeq++; widget.close(); return; } // invalidate any in-flight response
      runSearch(seg);
    });
  }

  window.attachPlaceAutocomplete = attachPlaceAutocomplete;
  window.attachMultiValueAutocomplete = attachMultiValueAutocomplete;

  // Auto-init from data attributes instead of a per-page inline <script>
  // block -- keeps every page's Content-Security-Policy free of
  // 'unsafe-inline' for scripts.
  //   data-autocomplete-name        -> single mode: id of the field itself
  //   data-autocomplete-category    -> (single mode) id of category field to fill
  //   data-autocomplete-location    -> id of location field: fills it (single
  //                                    mode) and/or supplies the geocode bias
  //   data-autocomplete-multi       -> multi mode: id of the field itself
  //                                    (data-autocomplete-location still
  //                                    supplies the bias, no autofill)
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-autocomplete-name]").forEach(function (input) {
      attachPlaceAutocomplete(
        input.id,
        input.getAttribute("data-autocomplete-category") || null,
        input.getAttribute("data-autocomplete-location") || null
      );
    });
    document.querySelectorAll("[data-autocomplete-multi]").forEach(function (input) {
      attachMultiValueAutocomplete(input.id, input.getAttribute("data-autocomplete-location") || null);
    });
  });
})();
