(function () {
  "use strict";
  var rows = [];
  var loaded = false;
  var failed = false;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function t(key) {
    return window.AILAB ? window.AILAB.t(key) : key;
  }

  function countLabel(count) {
    var space = window.AILAB && window.AILAB.lang === "en" ? " " : "";
    return count + space + t(count === 1 ? "seminars_count_one" : "seminars_count");
  }

  function dateParts(value) {
    var date = new Date(value);
    if (isNaN(date)) return { date: value, time: "" };
    var locale = window.AILAB && window.AILAB.lang === "en" ? "en-US" : "ko-KR";
    return {
      date: new Intl.DateTimeFormat(locale, {
        timeZone: "Asia/Seoul", year: "numeric", month: "short", day: "numeric"
      }).format(date),
      time: new Intl.DateTimeFormat(locale, {
        timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit"
      }).format(date)
    };
  }

  function fileSize(bytes) {
    var number = Number(bytes) || 0;
    if (number < 1024) return number + " B";
    if (number < 1024 * 1024) return (number / 1024).toFixed(1) + " KB";
    return (number / 1024 / 1024).toFixed(1) + " MB";
  }

  function safeFileUrl(value) {
    var url = String(value || "");
    return url.indexOf("/seminar-files/") === 0 ? url : "#";
  }

  function render() {
    var list = document.getElementById("seminar-list");
    var status = document.getElementById("seminar-status");
    if (!list) return;
    if (failed) {
      list.innerHTML = '<div class="seminar-empty seminar-error"><span aria-hidden="true">!</span><h3>' +
        esc(t("seminars_error_h")) + "</h3><p>" + esc(t("seminars_error_p")) + "</p></div>";
      if (status) status.textContent = t("seminars_offline");
      return;
    }
    if (!loaded) {
      list.innerHTML = '<p class="seminar-loading">' + esc(t("seminars_loading")) + "</p>";
      return;
    }
    if (!rows.length) {
      list.innerHTML = '<div class="seminar-empty"><span aria-hidden="true">01</span><h3>' +
        esc(t("seminars_empty_h")) + "</h3><p>" + esc(t("seminars_empty_p")) + "</p></div>";
      if (status) status.textContent = countLabel(0);
      return;
    }
    list.innerHTML = rows.map(function (row, index) {
      var date = dateParts(row.uploaded_at);
      var displayDay = String(row.presented_on || row.uploaded_at || "").slice(0, 10);
      var dayParts = displayDay.split("-");
      var files = Array.isArray(row.files) ? row.files : [];
      return '<article class="seminar-item" id="seminar-' + esc(row.id) + '">' +
        '<div class="seminar-date-tile" aria-hidden="true"><span>' + esc(dayParts.slice(0, 2).join(".")) +
          '</span><strong>' + esc(dayParts[2] || "—") + '</strong><small>' + esc(t(row.presented_on ? "seminars_presented" : "seminars_uploaded")) + '</small></div>' +
        '<div class="seminar-body">' +
          '<div class="seminar-card-top"><span class="seminar-material-badge">' + esc(t("seminars_materials")) +
            '</span><span class="seminar-number" aria-hidden="true">' + String(index + 1).padStart(2, "0") + '</span></div>' +
          '<h3>' + esc(row.title) + "</h3>" +
          (row.presented_on ? '<p class="seminar-presented-date">' + esc(t("seminars_presented")) + ' <time datetime="' + esc(row.presented_on) + '">' + esc(row.presented_on) + '</time></p>' : '') +
          (row.summary ? '<p class="seminar-summary">' + esc(row.summary) + "</p>" : "") +
          '<div class="seminar-meta"><span class="seminar-presenter"><span class="seminar-avatar" aria-hidden="true">' +
            esc(Array.from(String(row.presenter || ""))[0] || "•") + '</span><span>' + esc(t("seminars_presenter")) + '</span><strong>' + esc(row.presenter) + '</strong></span>' +
            '<span class="seminar-upload-time">' + esc(t("seminars_uploaded")) + ' <time datetime="' + esc(row.uploaded_at) + '">' + esc(date.date) +
            (date.time ? " · " + esc(date.time) + " KST" : "") + "</time></span></div>" +
          '<div class="seminar-files">' + files.map(function (file) {
            var ext = String(file.name || "").split(".").pop().toUpperCase();
            return '<a class="seminar-file" href="' + esc(safeFileUrl(file.url)) + '">' +
              '<span class="seminar-file-icon" aria-hidden="true">' + esc(ext.slice(0, 5)) + '</span><span class="seminar-file-info"><strong>' + esc(file.name) +
              '</strong><small>' + esc(fileSize(file.size)) + " · " + esc(t("seminars_download")) + '</small></span><span class="seminar-file-arrow" aria-hidden="true">↓</span></a>';
          }).join("") + "</div>" +
        "</div></article>";
    }).join("");
    if (status) status.textContent = countLabel(rows.length);
  }

  function load() {
    fetch("/api/seminars", { cache: "no-store", headers: { "Accept": "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.json();
      })
      .then(function (data) {
        rows = Array.isArray(data) ? data.slice().sort(function (a, b) {
          return String(b.uploaded_at || "").localeCompare(String(a.uploaded_at || ""));
        }) : [];
        loaded = true;
        failed = false;
        render();
      })
      .catch(function () {
        loaded = true;
        failed = true;
        render();
      });
  }

  var guide = document.getElementById("upload-guide");
  var guideLink = document.querySelector(".seminar-guide-link");
  if (guideLink) guideLink.addEventListener("click", function () { guide.open = true; });
  if (guide && location.hash === "#upload-guide") guide.open = true;
  var copy = document.getElementById("copy-seminar-template");
  if (copy) copy.addEventListener("click", function () {
    var status = document.getElementById("seminar-copy-status");
    var value = document.getElementById("seminar-template").textContent;
    if (!navigator.clipboard) { status.textContent = t("seminars_copy_fail"); return; }
    navigator.clipboard.writeText(value).then(function () { status.textContent = t("seminars_copied"); })
      .catch(function () { status.textContent = t("seminars_copy_fail"); });
  });

  document.addEventListener("ailab:rendered", render);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
  load();
  setInterval(function () { if (!document.hidden) load(); }, 60000);
})();
