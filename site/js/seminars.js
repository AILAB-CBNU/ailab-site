(function () {
  "use strict";
  var rows = [];
  var loaded = false;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function t(key) {
    return window.AILAB ? window.AILAB.t(key) : key;
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
    if (!loaded) {
      list.innerHTML = '<p class="seminar-loading">' + esc(t("seminars_loading")) + "</p>";
      return;
    }
    if (!rows.length) {
      list.innerHTML = '<div class="seminar-empty"><span aria-hidden="true">01</span><h3>' +
        esc(t("seminars_empty_h")) + "</h3><p>" + esc(t("seminars_empty_p")) + "</p></div>";
      if (status) status.textContent = "0 " + t("seminars_count");
      return;
    }
    list.innerHTML = rows.map(function (row, index) {
      var date = dateParts(row.uploaded_at);
      var files = Array.isArray(row.files) ? row.files : [];
      return '<article class="seminar-item">' +
        '<div class="seminar-index" aria-hidden="true">' + String(index + 1).padStart(2, "0") + "</div>" +
        '<div class="seminar-body">' +
          '<div class="seminar-meta"><time datetime="' + esc(row.uploaded_at) + '">' + esc(date.date) +
            (date.time ? '<span>' + esc(date.time) + " KST</span>" : "") + "</time>" +
            '<span class="seminar-presenter"><span>' + esc(t("seminars_presenter")) + "</span> " + esc(row.presenter) + "</span></div>" +
          '<h3>' + esc(row.title) + "</h3>" +
          (row.summary ? '<p class="seminar-summary">' + esc(row.summary) + "</p>" : "") +
          '<div class="seminar-files">' + files.map(function (file) {
            return '<a class="seminar-file" href="' + esc(safeFileUrl(file.url)) + '">' +
              '<span class="seminar-file-icon" aria-hidden="true">↓</span><span><strong>' + esc(file.name) +
              '</strong><small>' + esc(fileSize(file.size)) + " · " + esc(t("seminars_download")) + "</small></span></a>";
          }).join("") + "</div>" +
        "</div></article>";
    }).join("");
    if (status) status.textContent = rows.length + " " + t("seminars_count");
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
        render();
      })
      .catch(function () {
        loaded = true;
        rows = [];
        var list = document.getElementById("seminar-list");
        var status = document.getElementById("seminar-status");
        if (list) list.innerHTML = '<div class="seminar-empty seminar-error"><span aria-hidden="true">!</span><h3>' +
          esc(t("seminars_error_h")) + "</h3><p>" + esc(t("seminars_error_p")) + "</p></div>";
        if (status) status.textContent = t("seminars_offline");
      });
  }

  document.addEventListener("ailab:rendered", render);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) load(); });
  load();
  setInterval(function () { if (!document.hidden) load(); }, 60000);
})();
