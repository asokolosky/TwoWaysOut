// "Smoke clears" transition for the /check report.
// While the HTMX request is in flight, .report-stage gets .is-loading (smoke layer shows,
// old content blurs). When the report is swapped in, the smoke fades and the report
// un-blurs. Without JavaScript the form posts normally and none of this runs.
(function () {
  "use strict";

  var stage = document.querySelector("[data-report-stage]");
  var report = document.getElementById("report");
  if (!stage || !report) return;
  var form = document.querySelector("form[hx-target='#report']");

  function fromForm(evt) {
    return form && evt.detail && evt.detail.elt === form;
  }

  document.body.addEventListener("htmx:beforeRequest", function (evt) {
    if (!fromForm(evt)) return;
    report.classList.remove("smoke-reveal");
    stage.classList.add("is-loading");
  });

  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.detail.target !== report) return;
    stage.classList.remove("is-loading");
    // Restart the reveal animation.
    void report.offsetWidth;
    report.classList.add("smoke-reveal");
  });

  // Errors, timeouts, and aborted requests: clear the smoke without a reveal.
  document.body.addEventListener("htmx:afterRequest", function (evt) {
    if (!fromForm(evt)) return;
    if (!evt.detail.successful || evt.detail.failed) {
      stage.classList.remove("is-loading");
    }
  });

  report.addEventListener("animationend", function () {
    report.classList.remove("smoke-reveal");
  });
})();
