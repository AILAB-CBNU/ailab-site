(function () {
  "use strict";

  var PAGES = [
    { id: "common", label: "헤더·푸터", file: "index.html", eyebrow: "COMMON", description: "모든 페이지에 공통으로 표시되는 텍스트와 링크입니다." },
    { id: "home", label: "홈", file: "index.html", eyebrow: "HOME", description: "첫 화면의 소개, 연구 분야, 소식, 논문과 참여 안내를 편집합니다." },
    { id: "research", label: "연구", file: "research.html", eyebrow: "RESEARCH", description: "연구 분야와 관련 설명을 편집합니다." },
    { id: "people", label: "구성원", file: "people.html", eyebrow: "PEOPLE", description: "교수, 연구원, 학생과 졸업생 정보를 편집합니다." },
    { id: "publications", label: "논문", file: "publications.html", eyebrow: "PUBLICATIONS", description: "논문 제목, 저자, 학술지와 관련 링크를 편집합니다." },
    { id: "projects", label: "과제", file: "projects.html", eyebrow: "PROJECTS", description: "연구 과제명, 기간, 지원기관과 역할을 편집합니다." },
    { id: "news", label: "소식", file: "news.html", eyebrow: "NEWS", description: "연구실 소식의 제목, 내용과 분류를 편집합니다." },
    { id: "seminars", label: "세미나 안내", file: "seminars.html", eyebrow: "SEMINARS", description: "세미나 자료실의 안내 문구를 편집합니다. 업로드된 자료는 ‘세미나 자료 관리’에서 관리하세요." },
    { id: "seminar-files", label: "세미나 자료 관리", file: "seminars.html", eyebrow: "SEMINAR MATERIALS", description: "업로드 날짜순으로 자료를 확인하고 잘못 올린 자료를 삭제합니다.", manage: true },
    { id: "contact", label: "연락처", file: "contact.html", eyebrow: "CONTACT", description: "주소, 연락처, 지원 안내와 연결 주소를 편집합니다." }
  ];

  var state = {
    page: PAGES[0],
    lang: "ko",
    content: null,
    items: [],
    dirty: false,
    seminars: [],
    seminarRequest: 0,
    confirmDelete: null,
    deleting: false
  };

  var loginView = document.getElementById("login-view");
  var editorView = document.getElementById("editor-view");
  var loginForm = document.getElementById("login-form");
  var loginMessage = document.getElementById("login-message");
  var setupNote = document.getElementById("setup-note");
  var pageList = document.getElementById("page-list");
  var iframe = document.getElementById("page-preview");
  var fieldList = document.getElementById("field-list");
  var loading = document.getElementById("loading-state");
  var search = document.getElementById("field-search");
  var saveButton = document.getElementById("save-button");
  var saveStatus = document.getElementById("save-status");
  var seminarManager = document.getElementById("seminar-manager");
  var seminarList = document.getElementById("seminar-management-list");
  var seminarMessage = document.getElementById("seminar-manager-message");
  var refreshSeminars = document.getElementById("refresh-seminars");

  function api(url, options) {
    options = options || {};
    options.credentials = "same-origin";
    options.headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) {
          var error = new Error(body.error || "request_failed");
          error.status = response.status;
          throw error;
        }
        return body;
      });
    });
  }

  function showLogin(configured) {
    loginView.hidden = false;
    editorView.hidden = true;
    setupNote.hidden = configured !== false;
    loginForm.querySelector("button").disabled = configured === false;
  }

  function ensureContent() {
    state.content = state.content || { version: 1, global: { ko: {}, en: {} }, pages: {} };
    state.content.global = state.content.global || { ko: {}, en: {} };
    state.content.global.ko = state.content.global.ko || {};
    state.content.global.en = state.content.global.en || {};
    PAGES.slice(1).forEach(function (page) {
      state.content.pages[page.file] = state.content.pages[page.file] || { ko: {}, en: {} };
      state.content.pages[page.file].ko = state.content.pages[page.file].ko || {};
      state.content.pages[page.file].en = state.content.pages[page.file].en || {};
    });
  }

  function currentMap(scope) {
    ensureContent();
    if (scope === "global") return state.content.global[state.lang];
    return state.content.pages[state.page.file][state.lang];
  }

  function setDirty(value) {
    state.dirty = value;
    saveButton.disabled = !value;
    saveStatus.textContent = value ? "저장되지 않은 변경사항" : "저장된 상태";
    saveStatus.className = value ? "dirty" : "saved";
  }

  function loadPreview() {
    if (state.page.manage) {
      document.getElementById("open-page").href = "seminars.html?lang=ko";
      loadSeminars();
      return;
    }
    state.items = [];
    fieldList.innerHTML = "";
    loading.hidden = false;
    loading.textContent = "페이지에서 편집 항목을 불러오는 중입니다.";
    search.value = "";
    iframe.src = state.page.file + "?cms-edit=1&lang=" + state.lang + "&v=" + Date.now();
    document.getElementById("open-page").href = state.page.file + (state.lang === "en" ? "?lang=en" : "");
  }

  function selectPage(id) {
    var next = PAGES.find(function (page) { return page.id === id; }) || PAGES[0];
    state.page = next;
    pageList.querySelectorAll("button").forEach(function (button) {
      button.setAttribute("aria-current", button.dataset.page === id ? "page" : "false");
    });
    document.getElementById("section-eyebrow").textContent = next.eyebrow;
    document.getElementById("section-title").textContent = next.label;
    document.getElementById("section-description").textContent = next.description;
    document.getElementById("text-editor-grid").hidden = !!next.manage;
    document.querySelector(".save-area").hidden = !!next.manage;
    document.querySelector(".language-box").hidden = !!next.manage;
    seminarManager.hidden = !next.manage;
    state.confirmDelete = null;
    setDirty(false);
    loadPreview();
  }

  function pageNavigation() {
    pageList.innerHTML = PAGES.map(function (page, index) {
      return '<button type="button" data-page="' + page.id + '" aria-current="' + (index === 0 ? "page" : "false") + '">' + page.label + "</button>";
    }).join("");
  }

  function labelFor(item, index) {
    if (item.kind === "link") return (item.context ? "링크 · " + item.context : "링크 주소") + " · " + (index + 1);
    if (item.kind === "placeholder") return "입력 안내 문구 · " + (index + 1);
    var preview = (item.value || item.original || "텍스트").replace(/\s+/g, " ").slice(0, 46);
    return item.tag.toUpperCase() + " · " + preview;
  }

  function renderFields() {
    var query = search.value.trim().toLowerCase();
    var wantedScope = state.page.id === "common" ? "global" : "page";
    var seen = {};
    var rows = state.items.filter(function (item) {
      if (item.scope !== wantedScope) return false;
      if (state.page.id === "seminars" && /^#seminar-(list|status)(?:\/|@|$)/.test(item.key)) return false;
      var id = item.scope + ":" + item.key;
      if (seen[id]) return false;
      seen[id] = true;
      return !query || ((item.value || "") + " " + (item.context || "") + " " + item.key).toLowerCase().indexOf(query) > -1;
    });
    document.getElementById("field-count").textContent = rows.length + "개";
    loading.hidden = true;
    if (!rows.length) {
      fieldList.innerHTML = '<div class="empty-fields">편집할 항목이 없습니다.</div>';
      return;
    }
    var groups = {};
    rows.forEach(function (item) { (groups[item.region] = groups[item.region] || []).push(item); });
    var names = { header: "공통 헤더", page: state.page.label + " 본문", footer: "공통 푸터" };
    fieldList.innerHTML = Object.keys(groups).map(function (region) {
      return '<section class="field-group"><h2>' + names[region] + '</h2>' + groups[region].map(function (item, index) {
        var value = currentMap(item.scope)[item.key];
        if (typeof value !== "string") value = item.value;
        var control = item.kind === "text" && value.length > 70
          ? '<textarea class="cms-field">' + escapeHtml(value) + "</textarea>"
          : '<input class="cms-field" type="text" value="' + escapeAttr(value) + '">';
        return '<article class="field-card" data-scope="' + item.scope + '" data-key="' + escapeAttr(item.key) + '" data-original="' + escapeAttr(item.original || "") + '">' +
          '<div class="field-head"><span class="field-label">' + escapeHtml(labelFor(item, index)) + '</span><span class="field-kind">' + (item.kind === "link" ? "URL" : "TEXT") + "</span></div>" +
          control + '<div class="field-actions"><button class="reset-field" type="button">기본값으로 되돌리기</button></div></article>';
      }).join("") + "</section>";
    }).join("");
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>]/g, function (char) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[char]; });
  }
  function escapeAttr(value) {
    return escapeHtml(value).replace(/"/g, "&quot;");
  }

  function seminarDate(value) {
    var date = new Date(value);
    if (isNaN(date.getTime())) return "업로드 날짜 없음";
    return new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(date) + " KST";
  }

  function setSeminarMessage(message, error) {
    seminarMessage.textContent = message;
    seminarMessage.classList.toggle("is-error", !!error);
  }

  function renderSeminars() {
    if (!state.seminars.length) {
      seminarList.innerHTML = '<div class="empty-fields">등록된 세미나 자료가 없습니다.</div>';
      return;
    }
    seminarList.innerHTML = state.seminars.map(function (row) {
      var id = String(row.id || "");
      var title = row.title || "제목 없는 자료";
      var files = Array.isArray(row.files) ? row.files : [];
      var confirming = state.confirmDelete === id;
      return '<article class="managed-seminar" data-seminar-id="' + escapeAttr(id) + '">' +
        '<div class="managed-seminar-heading"><div><p class="managed-seminar-date">' + escapeHtml(seminarDate(row.uploaded_at)) + '</p>' +
        '<h2>' + escapeHtml(title) + '</h2><p class="managed-seminar-presenter">발표자 ' + escapeHtml(row.presenter || "미지정") + '</p></div>' +
        '<button class="danger-outline" data-seminar-action="prepare" type="button"' + (!id || state.deleting ? ' disabled' : '') +
        ' aria-label="' + escapeAttr(title + " 자료 삭제") + '">자료 삭제</button></div>' +
        '<ul class="managed-seminar-files">' + files.map(function (file) {
          return '<li>' + escapeHtml(file.name || "첨부파일") + '</li>';
        }).join("") + '</ul>' +
        (confirming ? '<div class="seminar-delete-confirm" role="group" aria-label="자료 삭제 확인"><p><strong>' + escapeHtml(title) +
          '</strong> 자료와 첨부파일을 웹사이트에서 삭제할까요?</p><p class="delete-detail">삭제한 자료는 자동으로 다시 수집되지 않습니다. Discord 원본 메시지는 삭제되지 않습니다.</p>' +
          '<div class="seminar-delete-actions"><button class="quiet" data-seminar-action="cancel" type="button"' + (state.deleting ? ' disabled' : '') + '>취소</button>' +
          '<button class="danger" data-seminar-action="confirm" type="button"' + (state.deleting ? ' disabled' : '') + '>' + (state.deleting ? '삭제 중…' : '삭제 확인') + '</button></div></div>' : '') + '</article>';
    }).join("");
  }

  function loadSeminars(keepMessage) {
    var request = ++state.seminarRequest;
    refreshSeminars.disabled = true;
    if (!keepMessage) setSeminarMessage("세미나 자료를 불러오는 중입니다.");
    return api("/api/seminars", { cache: "no-store" }).then(function (rows) {
      if (request !== state.seminarRequest) return;
      if (!Array.isArray(rows)) throw new Error("invalid_seminar_list");
      state.seminars = rows.slice().sort(function (a, b) {
        return String(b.uploaded_at || "").localeCompare(String(a.uploaded_at || ""));
      });
      state.confirmDelete = null;
      renderSeminars();
      if (!keepMessage) setSeminarMessage("총 " + rows.length + "개의 세미나 자료");
    }).catch(function () {
      if (request === state.seminarRequest) setSeminarMessage("자료 목록을 불러오지 못했습니다. 웹 서버 연결을 확인하고 새로고침하세요.", true);
    }).finally(function () {
      if (request === state.seminarRequest) refreshSeminars.disabled = false;
    });
  }

  function deleteSeminar(id) {
    var row = state.seminars.find(function (item) { return String(item.id) === id; });
    if (!row || state.deleting || state.confirmDelete !== id) return;
    state.deleting = true;
    refreshSeminars.disabled = true;
    renderSeminars();
    api("/api/admin/seminars/" + encodeURIComponent(id), { method: "DELETE" })
      .then(function (result) {
        if (result.ok !== true) throw new Error("delete_not_confirmed");
        setSeminarMessage('“' + (row.title || "제목 없는 자료") + '” 자료를 삭제했습니다.');
        state.confirmDelete = null;
        if (iframe.src.indexOf("seminars.html") !== -1) iframe.src = "seminars.html?cms-edit=1&lang=" + state.lang + "&v=" + Date.now();
        return loadSeminars(true);
      })
      .catch(function (error) {
        var message = "삭제하지 못했습니다. 서버 연결을 확인한 뒤 다시 시도하세요.";
        if (error.status === 401) {
          loginMessage.textContent = "로그인이 만료되었습니다. 다시 로그인해 주세요.";
          showLogin(true);
        } else if (error.status === 403) {
          message = "삭제 권한 또는 접속 주소를 확인할 수 없습니다. 홈페이지와 같은 주소의 관리자 페이지에서 다시 로그인하세요.";
        } else if (error.status === 404) {
          message = "자료를 찾을 수 없거나 서버가 삭제 기능을 지원하지 않습니다. 목록을 새로고침한 뒤에도 자료가 남아 있으면 서버 업데이트를 적용하세요.";
        } else if (error.status === 405 || error.status === 501) {
          message = "현재 서버는 자료 삭제 기능을 지원하지 않습니다. 서버 업데이트를 적용하고 홈페이지 서버를 다시 실행하세요.";
        }
        setSeminarMessage(message, true);
      }).finally(function () {
        state.deleting = false;
        refreshSeminars.disabled = false;
        renderSeminars();
      });
  }

  pageList.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-page]");
    if (button) selectPage(button.dataset.page);
  });

  refreshSeminars.addEventListener("click", function () { if (!state.deleting) loadSeminars(); });

  seminarList.addEventListener("click", function (event) {
    var button = event.target.closest("button[data-seminar-action]");
    if (!button || state.deleting) return;
    var card = button.closest("[data-seminar-id]");
    var id = card.dataset.seminarId;
    if (button.dataset.seminarAction === "confirm") { deleteSeminar(id); return; }
    state.confirmDelete = button.dataset.seminarAction === "prepare" ? id : null;
    renderSeminars();
    var cards = seminarList.querySelectorAll("[data-seminar-id]");
    Array.prototype.forEach.call(cards, function (node) {
      if (node.dataset.seminarId !== id) return;
      var focusTarget = node.querySelector('[data-seminar-action="' + (state.confirmDelete ? "cancel" : "prepare") + '"]');
      if (focusTarget) focusTarget.focus();
    });
  });

  function openEditor() {
    return api("/api/admin/content").then(function (content) {
      state.content = content;
      ensureContent();
      loginView.hidden = true;
      editorView.hidden = false;
      pageNavigation();
      selectPage("common");
    }).catch(function (error) {
      if (error.status === 401) showLogin(true);
      else throw error;
    });
  }

  loginForm.addEventListener("submit", function (event) {
    event.preventDefault();
    loginMessage.textContent = "로그인 중입니다.";
    api("/api/admin/login", { method: "POST", body: JSON.stringify({ password: document.getElementById("admin-password").value }) })
      .then(function () { document.getElementById("admin-password").value = ""; return openEditor(); })
      .catch(function (error) {
        loginMessage.textContent = error.status === 429 ? "로그인 시도가 너무 많습니다. 10분 뒤 다시 시도하세요." : "비밀번호가 올바르지 않습니다.";
      });
  });

  document.querySelectorAll("[data-lang]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.lang = button.dataset.lang;
      document.querySelectorAll("[data-lang]").forEach(function (node) { node.setAttribute("aria-pressed", String(node === button)); });
      setDirty(false);
      loadPreview();
    });
  });

  fieldList.addEventListener("input", function (event) {
    var input = event.target.closest(".cms-field");
    if (!input) return;
    var card = input.closest(".field-card");
    currentMap(card.dataset.scope)[card.dataset.key] = input.value;
    setDirty(true);
    iframe.contentWindow.postMessage({ type: "ailab-cms-preview", scope: card.dataset.scope, key: card.dataset.key, value: input.value }, location.origin);
  });

  fieldList.addEventListener("focusin", function (event) {
    var input = event.target.closest(".cms-field");
    if (!input) return;
    var card = input.closest(".field-card");
    iframe.contentWindow.postMessage({ type: "ailab-cms-focus", scope: card.dataset.scope, key: card.dataset.key }, location.origin);
  });

  fieldList.addEventListener("click", function (event) {
    var button = event.target.closest(".reset-field");
    if (!button) return;
    var card = button.closest(".field-card");
    var input = card.querySelector(".cms-field");
    input.value = card.dataset.original;
    delete currentMap(card.dataset.scope)[card.dataset.key];
    setDirty(true);
    iframe.contentWindow.postMessage({ type: "ailab-cms-preview", scope: card.dataset.scope, key: card.dataset.key, value: card.dataset.original }, location.origin);
  });

  search.addEventListener("input", renderFields);

  saveButton.addEventListener("click", function () {
    saveButton.disabled = true;
    saveStatus.textContent = "저장 중…";
    api("/api/admin/content", { method: "PUT", body: JSON.stringify(state.content) })
      .then(function () { setDirty(false); saveStatus.textContent = "저장 완료"; })
      .catch(function (error) {
        saveButton.disabled = false;
        saveStatus.textContent = error.status === 401 ? "로그인이 만료되었습니다." : "저장하지 못했습니다.";
        if (error.status === 401) showLogin(true);
      });
  });

  document.getElementById("logout-button").addEventListener("click", function () {
    api("/api/admin/logout", { method: "POST", body: "{}" }).finally(function () { showLogin(true); });
  });

  window.addEventListener("message", function (event) {
    if (event.origin !== location.origin || event.source !== iframe.contentWindow || !event.data || event.data.type !== "ailab-cms-ready") return;
    if (state.page.manage) return;
    if (event.data.page !== state.page.file || event.data.lang !== state.lang) return;
    state.items = event.data.items || [];
    if (!state.dirty) renderFields();
  });

  api("/api/admin/status").then(function (status) {
    if (!status.configured) showLogin(false);
    else if (status.authenticated) openEditor();
    else showLogin(true);
  }).catch(function () {
    showLogin(true);
    loginMessage.textContent = "관리자 API에 연결할 수 없습니다. 웹 서버 실행 상태를 확인하세요.";
  });
})();
