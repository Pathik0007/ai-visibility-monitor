/*
 * Smart form fields (external file -- the CSP forbids inline scripts):
 *
 * 1. Google Maps links. Paste a Google Maps / Business Profile link into the
 *    link box (or straight into Business name / Competitors) and it's read
 *    right away via /api/resolve-link: the business fills Name, Category and
 *    Location; a competitor link adds that competitor to the list.
 *
 * 2. Competitor sanity check. Every competitor whose category we know (picked
 *    from suggestions or added by link) is compared with your category via
 *    /api/category-check. A different kind of business (cafe vs car wash) is
 *    flagged with a one-click Remove; a different specialty (plumber vs
 *    electrician) gets a softer note. Categories travel with the form in a
 *    hidden `competitor_meta` field so the server makes the same call.
 *
 * Markup contract (per form, marked data-smart-form):
 *   [data-link-for="business"]     link box that fills the business fields
 *   [data-link-for="competitor"]   link box that adds a competitor
 *   input[name=competitor_meta]    hidden JSON {name: category}
 *   data-name / data-category / data-location / data-competitors on the form
 *   give the ids of those fields.
 */
(function () {
  "use strict";

  var LINK_RE = /^(https?:\/\/)?([a-z0-9-]+\.)*(google\.[a-z.]+|goo\.gl|g\.page|g\.co|share\.google)\//i;

  function debounce(fn, wait) {
    var t = null;
    return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, wait); };
  }
  function splitList(v) { return (v || "").split(",").map(function (x) { return x.trim(); }).filter(Boolean); }
  function an(w) { return /^[aeiou]/i.test(w || "") ? "an " + w : "a " + w; }
  function norm(s) { return (s || "").toLowerCase().replace(/[^a-z0-9]+/g, ""); }

  function setStatus(el, cls, text) {
    if (!el) return;
    el.className = "link-status " + (cls || "");
    el.textContent = text || "";
  }

  function initForm(form) {
    var $ = function (id) { return id ? document.getElementById(id) : null; };
    var nameEl = $(form.getAttribute("data-name"));
    var catEl = $(form.getAttribute("data-category"));
    var locEl = $(form.getAttribute("data-location"));
    var compEl = $(form.getAttribute("data-competitors"));
    var webEl = form.querySelector("input[name=website]");
    var metaEl = form.querySelector("input[name=competitor_meta]");
    var meta = {};
    try { meta = JSON.parse((metaEl && metaEl.value) || "{}") || {}; } catch (e) { meta = {}; }

    // ---------- competitor category warnings ----------
    var warnBox = null;
    if (compEl) {
      warnBox = document.createElement("div");
      warnBox.className = "comp-warnings";
      warnBox.setAttribute("aria-live", "polite");
      var anchor = compEl.closest(".ac-wrap") || compEl;
      anchor.parentNode.insertBefore(warnBox, anchor.nextSibling);
    }

    function saveMeta() {
      if (!metaEl) return;
      var present = {};
      splitList(compEl ? compEl.value : "").forEach(function (n) { present[norm(n)] = n; });
      var kept = {};
      Object.keys(meta).forEach(function (k) { if (present[norm(k)]) kept[present[norm(k)]] = meta[k]; });
      metaEl.value = JSON.stringify(kept);
      return kept;
    }

    function removeCompetitor(name) {
      var list = splitList(compEl.value).filter(function (n) { return norm(n) !== norm(name); });
      compEl.value = list.join(", ") + (list.length ? ", " : "");
      delete meta[name];
      runCheck();
    }

    var checkSeq = 0;
    var runCheck = debounce(function () {
      if (!compEl || !warnBox) return;
      var kept = saveMeta();
      var names = Object.keys(kept || {});
      var business = catEl ? catEl.value.trim() : "";
      var seq = ++checkSeq;
      if (!names.length || !business) { warnBox.innerHTML = ""; return; }
      var url = "/api/category-check?business=" + encodeURIComponent(business) +
        "&name=" + encodeURIComponent(nameEl ? nameEl.value.trim() : "") +
        names.map(function (n) { return "&c=" + encodeURIComponent(kept[n]) + "&n=" + encodeURIComponent(n); }).join("");
      fetch(url).then(function (r) { return r.ok ? r.json() : { results: [] }; }).then(function (data) {
        if (seq !== checkSeq) return;
        warnBox.innerHTML = "";
        (data.results || []).forEach(function (res, i) {
          if (res.verdict !== "mismatch" && res.verdict !== "different_specialty") return;
          var name = names[i];
          var business = res.business_category || catEl.value.trim();
          var row = document.createElement("div");
          row.className = "comp-warn" + (res.verdict === "different_specialty" ? " soft" : "");
          var msg = document.createElement("span");
          msg.textContent = res.verdict === "mismatch"
            ? "⚠ " + name + " is " + an(res.competitor_category) + " (" + (res.competitor_group || "").toLowerCase() +
              "), not " + an(business) + ". AI assistants won't recommend one instead of the other, so it won't be compared."
            : (res.group_key === "food"
              ? name + " is " + an(res.competitor_category) + " \u2014 different food from " + an(business) +
                ". You'll only compete on broad questions, so treat it as a partial competitor."
              : name + " is " + an(res.competitor_category) + " \u2014 a different specialty from " + business +
                ". Customers rarely choose between them.");
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = "Remove";
          btn.addEventListener("click", function () { removeCompetitor(name); });
          row.appendChild(msg);
          row.appendChild(btn);
          warnBox.appendChild(row);
        });
      }).catch(function () {});
    }, 300);

    if (compEl) compEl.addEventListener("input", runCheck);
    if (catEl) catEl.addEventListener("input", runCheck);
    form.addEventListener("avm:filled", function (e) {
      var d = e.detail || {};
      if (d.field === "competitor" && d.name && d.category) meta[d.name] = d.category;
      runCheck();
    });

    // ---------- Google Maps links ----------
    function resolve(url, onDone, statusEl) {
      setStatus(statusEl, "busy", "Reading link…");
      fetch("/api/resolve-link?url=" + encodeURIComponent(url))
        .then(function (r) { return r.ok ? r.json() : { ok: false, error: "Couldn't read that link right now." }; })
        .then(function (d) {
          if (!d || !d.ok) { setStatus(statusEl, "err", (d && d.error) || "Couldn't read that link."); return; }
          onDone(d);
        })
        .catch(function () { setStatus(statusEl, "err", "Couldn't read that link right now -- type the name instead."); });
    }

    function fillBusiness(d, statusEl) {
      if (nameEl) nameEl.value = d.name;
      if (catEl && d.category) catEl.value = d.category;
      if (webEl && d.website && !webEl.value.trim()) webEl.value = d.website;
      if (locEl && d.location) {
        locEl.value = d.location;
        locEl.dataset.userTyped = "1";
        var bias = window.avmLocationBias ? window.avmLocationBias(locEl) : null;
        if (bias && d.lat != null && d.lon != null && bias.setExact) bias.setExact(d.lat, d.lon, d.country);
        else if (bias && bias.refresh) bias.refresh(d.location);
      }
      var bits = [d.category, d.location].filter(Boolean).join(" · ");
      setStatus(statusEl, "ok", "✓ " + d.name + (bits ? " — " + bits : "") +
        (d.category ? "" : " (add a category below)"));
      runCheck();
    }

    function addCompetitor(d, statusEl) {
      if (!compEl) return;
      var list = splitList(compEl.value);
      var exists = list.some(function (n) { return norm(n) === norm(d.name); });
      if (!exists) list.push(d.name);
      compEl.value = list.join(", ") + ", ";
      if (d.category) meta[d.name] = d.category;
      setStatus(statusEl, "ok", (exists ? "Already listed: " : "✓ Added ") + d.name + (d.category ? " (" + d.category + ")" : ""));
      runCheck();
    }

    form.querySelectorAll("[data-link-for]").forEach(function (linkEl) {
      var kind = linkEl.getAttribute("data-link-for");
      var statusEl = document.getElementById(linkEl.id + "-status");
      var lastUrl = "";
      var go = debounce(function () {
        var v = linkEl.value.trim();
        if (!v) { setStatus(statusEl, "", ""); return; }
        if (!LINK_RE.test(v)) { setStatus(statusEl, "err", "Paste a Google Maps link (Share → Copy link)."); return; }
        if (v === lastUrl) return;
        lastUrl = v;
        resolve(v, function (d) {
          if (kind === "business") fillBusiness(d, statusEl);
          else { addCompetitor(d, statusEl); linkEl.value = ""; lastUrl = ""; }
        }, statusEl);
      }, 350);
      linkEl.addEventListener("input", go);
      // Enter in the link box reads the link -- it must not submit the form.
      linkEl.addEventListener("keydown", function (e) {
        if (e.key === "Enter") { e.preventDefault(); lastUrl = ""; go(); }
      });
      linkEl.addEventListener("paste", function () { setTimeout(go, 0); });
    });

    // Links pasted straight into the name / competitors boxes work too.
    function interceptPaste(el, kind) {
      if (!el) return;
      el.addEventListener("paste", function (e) {
        var text = (e.clipboardData || window.clipboardData);
        text = text ? text.getData("text") : "";
        if (!text || !LINK_RE.test(text.trim())) return;
        e.preventDefault();
        var statusEl = document.getElementById((kind === "business" ? form.getAttribute("data-business-link") : form.getAttribute("data-competitor-link")) + "-status");
        resolve(text.trim(), function (d) {
          if (kind === "business") fillBusiness(d, statusEl); else addCompetitor(d, statusEl);
        }, statusEl);
      });
    }
    interceptPaste(nameEl, "business");
    interceptPaste(compEl, "competitor");

    runCheck();
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-smart-form]").forEach(initForm);
  });
})();
