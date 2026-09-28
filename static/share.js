/* "Copy link" button on report pages (external file: CSP has no inline scripts). */
(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-copy-link]").forEach(function (btn) {
      var label = btn.textContent;
      btn.addEventListener("click", function () {
        var url = window.location.href;
        var done = function () {
          btn.textContent = "Link copied";
          setTimeout(function () { btn.textContent = label; }, 2000);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(done, function () { window.prompt("Copy this link:", url); });
        } else {
          window.prompt("Copy this link:", url);
        }
      });
    });
  });
})();
