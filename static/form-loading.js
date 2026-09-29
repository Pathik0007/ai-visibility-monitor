/*
 * Puts a submit button into a disabled "working..." state the instant a
 * form is submitted. A visibility check can take several seconds (it fans
 * out to multiple AI APIs) -- without this, a slow connection just looks
 * like the click did nothing, which invites a frustrated double-submit.
 */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    // Destructive actions ask first (no inline onsubmit -- CSP blocks inline JS).
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (e) {
        if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
      });
    });
    document.querySelectorAll("form[data-loading-text]").forEach(function (form) {
      form.addEventListener("submit", function () {
        var btn = form.querySelector("button[type=submit]");
        if (!btn || btn.disabled) return;
        btn.dataset.originalText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span> ' + form.getAttribute("data-loading-text");
      });
    });
  });
})();
