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
    { id: "seminars", label: "세미나", file: "seminars.html", eyebrow: "SEMINARS", description: "세미나 자료실의 안내 문구와 표시된 자료 정보를 편집합니다." },
    { id: "resources", label: "강의·자료", file: "resources.html", eyebrow: "RESOURCES", description: "강의명, 자료명과 연결 주소를 편집합니다." },
    { id: "contact", label: "연락처", file: "contact.html", eyebrow: "CONTACT", description: "주소, 연락처, 지원 안내와 연결 주소를 편집합니다." }
  ];

  var state = {
    page: PAGES[0],
    lang: "ko",
    content: null,
    items: [],
    dirty: false
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
    setDirty(false);
    loadPreview();
  }

  function pageNavigation() {
    pageList.innerHTML = PAGES.map(function (page, index) {
      return '<button type="button" data-page="' + page.id + '" aria-current="' + (index === 0 ? "page" : "false") + '">' + page.label + "</button>";
    }).join("");
    pageList.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-page]");
      if (button) selectPage(button.dataset.page);
    });
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
