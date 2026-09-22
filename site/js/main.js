/* =====================================================================
   AI Lab @ CBNU — 공통 스크립트
   네비/푸터 렌더, KO/EN 전환, 페이지별 데이터 렌더, 스크롤 리빌, 페이지 전환
   ===================================================================== */
(function () {
  "use strict";
  var D = window.SITE_DATA;
  if (!D) return;

  /* ---------- 언어 ---------- */
  var LANGS = ["ko", "en"];
  function readLang() {
    var q = new URLSearchParams(location.search).get("lang");
    if (q && LANGS.indexOf(q) > -1) return q;
    try { var s = localStorage.getItem("ailab-lang"); if (s && LANGS.indexOf(s) > -1) return s; } catch (e) {}
    return "ko";
  }
  var lang = readLang();
  function L(v) { // {ko,en} → 문자열
    if (v == null) return "";
    if (typeof v === "string" || typeof v === "number") return String(v);
    return v[lang] || v.ko || v.en || "";
  }
  function t(key) { var v = D.i18n[key]; return v ? L(v) : key; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function setLang(next) {
    lang = next;
    try { localStorage.setItem("ailab-lang", next); } catch (e) {}
    document.documentElement.lang = next;
    renderAll();
  }

  /* ---------- 공통 ---------- */
  var NAV = [
    ["index.html", "nav_home"], ["research.html", "nav_research"], ["people.html", "nav_people"],
    ["publications.html", "nav_publications"], ["projects.html", "nav_projects"],
    ["news.html", "nav_news"], ["seminars.html", "nav_seminars"],
    ["contact.html", "nav_contact"]
  ];
  function currentFile() {
    if (window.__AILAB_PAGE) return window.__AILAB_PAGE; // 단일 파일 미리보기용
    var f = location.pathname.split("/").pop();
    return f || "index.html";
  }
  var MARK = '<svg class="mark" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<circle cx="5" cy="12" r="2.2" fill="#2997ff"/><circle cx="19" cy="5" r="2.2" fill="#2997ff"/>' +
    '<circle cx="19" cy="19" r="2.2" fill="#2997ff"/><circle cx="12" cy="12" r="2.6" fill="#0071e3"/>' +
    '<path d="M7 12h3M14 11l3-4M14 13l3 4" stroke="#0071e3" stroke-width="1.4" stroke-linecap="round"/></svg>';

  function renderNav() {
    var el = document.getElementById("site-nav");
    if (!el) return;
    var cur = currentFile();
    var links = NAV.map(function (n) {
      var a = n[0] === cur ? ' aria-current="page"' : "";
      return '<a href="' + n[0] + '"' + a + ">" + esc(t(n[1])) + "</a>";
    }).join("");
    el.innerHTML =
      '<nav class="gn" aria-label="Global">' +
        '<div class="gn-inner">' +
          '<a class="gn-brand" href="index.html">' + MARK + "<span>" + esc(L(D.lab.short)) + '</span><span class="sub">' + esc(L(D.lab.affiliation)) + "</span></a>" +
          '<div class="gn-links">' + links + "</div>" +
          '<div class="gn-tools">' +
            '<button class="lang-btn" type="button" data-lang-toggle aria-label="Switch language">' + esc(t("lang_switch")) + "</button>" +
            '<button class="menu-btn" type="button" aria-expanded="false" aria-controls="gn-panel" aria-label="' + esc(t("menu")) + '"><span></span></button>' +
          "</div>" +
        "</div>" +
      "</nav>" +
      '<div class="gn-panel" id="gn-panel">' + links + "</div>";

    el.querySelector("[data-lang-toggle]").addEventListener("click", function () {
      setLang(lang === "ko" ? "en" : "ko");
    });
    var btn = el.querySelector(".menu-btn"), panel = el.querySelector(".gn-panel");
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", String(open));
      panel.classList.toggle("is-open", open);
      document.body.classList.toggle("menu-open", open);
    });
  }

  function renderFooter() {
    var el = document.getElementById("site-footer");
    if (!el) return;
    var y = new Date().getFullYear();
    var col = function (title, items) {
      return "<div><h3>" + esc(title) + "</h3><ul>" + items.map(function (i) {
        return '<li><a href="' + i[0] + '"' + (i[2] ? ' target="_blank" rel="noopener"' : "") + ">" + esc(i[1]) + "</a></li>";
      }).join("") + "</ul></div>";
    };
    el.innerHTML =
      '<footer class="footer"><div class="container">' +
        '<div class="footer-cols">' +
          col(t("footer_lab"), [["index.html", t("nav_home")], ["seminars.html", t("nav_seminars")], ["contact.html", t("nav_contact")], ["news.html", t("nav_news")]]) +
          col(t("footer_research"), D.research.map(function (r) { return ["research.html#" + r.id, L(r.title)]; })) +
          col(t("footer_people"), [["people.html", t("nav_people")], ["publications.html", t("nav_publications")], ["projects.html", t("nav_projects")]]) +
          col(t("footer_more"), [[D.lab.deptUrl, t("dept_site"), 1], [D.lab.scholarUrl, t("view_scholar"), 1], ["mailto:" + D.lab.email, t("email_us")], ["admin.html", lang === "ko" ? "관리자" : "Admin"]]) +
        "</div>" +
        '<div class="footer-fine">' +
          "<p>" + esc(L(D.lab.address)) + " · " + esc(D.lab.phone) + "</p>" +
          "<p>© " + y + " " + esc(L(D.lab.name)) + ", " + esc(L(D.lab.affiliation)) + ". " + esc(t("footer_rights")) + "</p>" +
        "</div>" +
      "</div></footer>";
  }

  function applyI18n(root) {
    (root || document).querySelectorAll("[data-i18n]").forEach(function (n) { n.textContent = t(n.getAttribute("data-i18n")); });
    (root || document).querySelectorAll("[data-i18n-placeholder]").forEach(function (n) { n.placeholder = t(n.getAttribute("data-i18n-placeholder")); });
    (root || document).querySelectorAll("[data-lab]").forEach(function (n) { n.textContent = L(D.lab[n.getAttribute("data-lab")]); });
    document.title = (document.body.getAttribute("data-title") ? t(document.body.getAttribute("data-title")) + " — " : "") + L(D.lab.name) + " · " + L(D.lab.affiliation);
  }

  /* ---------- 유틸 렌더 ---------- */
  function avatar(person, size) {
    var name = L(person.name);
    if (person.photo) return '<div class="avatar"><img src="' + esc(person.photo) + '" alt="' + esc(name) + '" loading="lazy"></div>';
    return '<div class="avatar" aria-hidden="true">' + esc(name.charAt(0)) + "</div>";
  }
  function fmtDate(iso) {
    if (/^\d{4}$/.test(iso)) return iso;
    if (/^\d{4}-\d{2}$/.test(iso)) return lang === "ko" ? iso.replace("-", ". ") + "." : new Date(iso + "-01T00:00:00").toLocaleDateString("en-US", {year:"numeric",month:"short"});
    var d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return iso;
    if (lang === "ko") return d.getFullYear() + ". " + (d.getMonth() + 1) + ". " + d.getDate() + ".";
    return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  }
  function pubItem(p) {
    var links = [];
    if (p.link) links.push('<a class="link" href="' + esc(p.link) + '" target="_blank" rel="noopener">' + esc(t("read_paper")) + "</a>");
    if (p.doi) links.push('<a href="https://doi.org/' + esc(p.doi) + '" target="_blank" rel="noopener">DOI ' + esc(p.doi) + "</a>");
    return '<li class="pub-item">' +
      '<div class="title">' + esc(p.title) + "</div>" +
      '<div class="authors">' + esc(p.authors) + "</div>" +
      '<div class="venue">' + esc(p.venue) + " · " + esc(t("type_" + p.type)) + "</div>" +
      (links.length ? '<div class="meta">' + links.join("") + "</div>" : "") +
    "</li>";
  }
  function sourceLink(url) {
    if (!/^https?:\/\//i.test(url || "")) return "";
    return '<a class="link" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(t("source_link")) + '</a>';
  }
  function newsItem(n) {
    return '<li><article class="news-item"' + (n.id ? ' id="' + esc(n.id) + '"' : '') + '>' +
      '<time class="date" datetime="' + esc(n.date) + '">' + esc(fmtDate(n.date)) + "</time>" +
      "<div>" +
        '<h3 class="title">' + esc(L(n.title)) + '<span class="pill pill--outline cat">' + esc(t("cat_" + n.category)) + "</span></h3>" +
        (L(n.body) ? '<p class="body body-sm">' + esc(L(n.body)) + "</p>" : "") + sourceLink(n.source) +
      "</div></article></li>";
  }
  function sortedNews() { return D.news.slice().sort(function (a, b) { return b.date.localeCompare(a.date); }); }
  function sortedPubs() { return D.publications.slice().sort(function (a, b) { return String(b.date || b.year).localeCompare(String(a.date || a.year)); }); }

  /* ---------- 페이지별 ---------- */
  var pages = {};

  pages.home = function () {
    var g = document.getElementById("home-research");
    if (g) g.innerHTML = D.research.map(function (r) {
      return '<li class="research-item" data-reveal>' +
        '<h3 class="heading-sm">' + esc(L(r.title)) + "</h3>" +
        "<p>" + esc(L(r.summary)) + "</p>" +
        '<a class="link" href="research.html#' + r.id + '">' + esc(t("learn_more")) + "</a></li>";
    }).join("");
    var n = document.getElementById("home-news");
    if (n) n.innerHTML = sortedNews().slice(0, 3).map(newsItem).join("");
    var p = document.getElementById("home-pubs");
    if (p) p.innerHTML = sortedPubs().filter(function (x) { return x.type !== "patent"; }).slice(0, 3).map(pubItem).join("");
    var pr = document.getElementById("home-prof");
    if (pr) {
      var P = D.professor;
      pr.innerHTML = avatar(P) +
        "<div>" +
          '<h3 class="name">' + esc(L(P.name)) + "</h3>" +
          '<p class="role">' + esc(L(P.title)) + "</p>" +
          '<p class="bio">' + esc(L(P.bio)) + "</p>" +
          '<div class="prof-contact"><a class="link" href="people.html">' + esc(t("learn_more")) + '</a><a href="' + esc(D.lab.scholarUrl) + '" target="_blank" rel="noopener">' + esc(t("view_scholar")) + "</a></div>" +
        "</div>";
    }
  };

  pages.research = function () {
    var el = document.getElementById("research-areas");
    if (!el) return;
    var pubs = sortedPubs();
    el.innerHTML = D.research.map(function (r, i) {
      var rel = pubs.filter(function (p) { return (p.areas || []).indexOf(r.id) > -1; }).slice(0, 4);
      return '<section class="section ' + (i % 2 ? "section--frost" : "section--white") + '" id="' + r.id + '"><div class="container area">' +
        "<div>" +
          '<h2 class="heading">' + esc(L(r.title)) + "</h2>" +
        "</div>" +
        "<div>" +
          '<p class="subheading summary">' + esc(L(r.summary)) + "</p>" +
          '<p class="detail">' + esc(L(r.detail)) + "</p>" +
          '<div class="kw" aria-label="' + esc(t("keywords")) + '">' + (r.keywords || []).map(function (k) { return '<span class="pill">' + esc(k) + "</span>"; }).join("") + "</div>" +
          (rel.length ? '<div class="related"><h3>' + esc(t("related_pubs")) + "</h3><ul>" + rel.map(function (p) {
            return '<li><span class="y">' + p.year + "</span>" + (p.link ? '<a href="' + esc(p.link) + '" target="_blank" rel="noopener">' + esc(p.title) + "</a>" : esc(p.title)) + "</li>";
          }).join("") + "</ul></div>" : "") +
        "</div>" +
      "</div></section>";
    }).join("");
  };

  pages.people = function () {
    var P = D.professor;
    var pc = document.getElementById("prof-card");
    if (pc) {
      var list = function (title, items, withYear) {
        return "<div><h3>" + esc(title) + "</h3><ul>" + items.map(function (i) {
          return '<li' + (i.id ? ' id="' + esc(i.id) + '"' : '') + '>' + (withYear && i.year ? '<span class="y">' + i.year + "</span>" : "") + esc(L(i)) + (i.source ? ' · ' + sourceLink(i.source) : '') + "</li>";
        }).join("") + "</ul></div>";
      };
      pc.innerHTML = avatar(P) +
        "<div>" +
          '<h2 class="name">' + esc(L(P.name)) + "</h2>" +
          '<p class="role">' + esc(L(P.title)) + "</p>" +
          '<div class="prof-contact">' +
            '<a href="mailto:' + esc(P.email) + '">' + esc(P.email) + "</a>" +
            '<span class="muted">' + esc(P.phone) + "</span>" +
            '<span class="muted">' + esc(t("office")) + " " + esc(L(P.office)) + "</span>" +
            '<a href="' + esc(D.lab.scholarUrl) + '" target="_blank" rel="noopener">' + esc(t("view_scholar")) + "</a>" +
          "</div>" +
          '<p class="bio">' + esc(L(P.bio)) + "</p>" +
          '<div class="prof-meta">' +
            list(t("education"), P.education) + list(t("career"), P.career) + list(t("awards"), P.awards, true) +
          "</div>" +
        "</div>";
    }
    var groups = document.getElementById("people-groups");
    if (groups) {
      var order = ["researcher", "combined", "phd", "ms", "intern"];
      groups.innerHTML = order.map(function (role) {
        var ms = D.members.filter(function (m) { return m.role === role; });
        if (!ms.length) return "";
        return '<section class="people-group"><h2 class="heading-sm">' + esc(t("role_" + role)) + '</h2><ul class="people-grid">' + ms.map(function (m) {
          return '<li class="person" id="member-' + esc(m.id || L(m.name)) + '" data-reveal>' + avatar(m) +
            '<div class="name">' + esc(L(m.name)) + "</div>" +
            '<div class="year">' + esc(L(m.year)) + "</div>" +
            (m.topic ? '<div class="topic">' + esc(L(m.topic)) + "</div>" : "") +
            (m.email ? '<a class="mail" href="mailto:' + esc(m.email) + '">' + esc(m.email) + "</a>" : "") +
          "</li>";
        }).join("") + "</ul></section>";
      }).join("");
    }
    var al = document.getElementById("alumni-list");
    if (al) al.innerHTML = D.alumni.map(function (a) {
      return '<li><span class="n">' + esc(L(a.name)) + '</span><span><span class="m">' + esc(L(a.degree)) + "</span>" + (L(a.now) ? " · " + esc(L(a.now)) : "") + "</span></li>";
    }).join("");
  };

  pages.publications = function () {
    var listEl = document.getElementById("pub-list");
    var typesEl = document.getElementById("pub-types");
    var yearsEl = document.getElementById("pub-years");
    var search = document.getElementById("pub-search");
    var countEl = document.getElementById("pub-count");
    if (!listEl) return;
    var state = pages.publications.state || (pages.publications.state = { type: "all", year: "all", q: "" });
    var all = sortedPubs();
    var types = ["all", "journal", "conference", "preprint", "book", "patent"].filter(function (x) { return x === "all" || all.some(function (p) { return p.type === x; }); });
    var years = ["all"].concat(all.map(function (p) { return p.year; }).filter(function (y, i, a) { return a.indexOf(y) === i; }));

    function pills(el, items, key, labelFn) {
      el.innerHTML = items.map(function (v) {
        return '<button type="button" class="filter-btn" data-v="' + v + '" aria-pressed="' + (state[key] === String(v)) + '">' + esc(labelFn(v)) + "</button>";
      }).join("");
      el.querySelectorAll(".filter-btn").forEach(function (b) {
        b.addEventListener("click", function () {
          state[key] = b.getAttribute("data-v");
          el.querySelectorAll(".filter-btn").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
          draw();
        });
      });
    }
    pills(typesEl, types, "type", function (v) { return v === "all" ? t("filter_all") : t("type_" + v); });
    pills(yearsEl, years, "year", function (v) { return v === "all" ? t("filter_all") : String(v); });
    if (search) search.oninput = function () { state.q = search.value.trim().toLowerCase(); draw(); };
    if (search) search.value = state.q;

    function draw() {
      var rows = all.filter(function (p) {
        if (state.type !== "all" && p.type !== state.type) return false;
        if (state.year !== "all" && String(p.year) !== state.year) return false;
        if (state.q) {
          var hay = (p.title + " " + p.authors + " " + p.venue).toLowerCase();
          if (hay.indexOf(state.q) < 0) return false;
        }
        return true;
      });
      if (countEl) countEl.textContent = rows.length + (lang === "ko" ? "편" : "");
      if (!rows.length) { listEl.innerHTML = '<p class="muted">' + esc(t("no_results")) + "</p>"; return; }
      var byYear = {};
      rows.forEach(function (p) { (byYear[p.year] = byYear[p.year] || []).push(p); });
      listEl.innerHTML = Object.keys(byYear).sort(function (a, b) { return b - a; }).map(function (y) {
        return '<div class="pub-year-head"><h2 class="heading-sm num">' + y + '</h2><span class="count">' + byYear[y].length + "</span></div>" +
          '<ul class="rule-list">' + byYear[y].map(pubItem).join("") + "</ul>";
      }).join("");
    }
    draw();
  };

  pages.projects = function () {
    var support = document.getElementById("research-support");
    if (support) support.innerHTML = (D.researchSupport || []).map(function (p) {
      return '<li class="support-card" id="' + esc(p.id) + '"><p class="eyebrow">' + esc(p.publicationYear) +
        (lang === "ko" ? ' · 논문' : ' · Publications') + '</p><h3>' + esc(L(p.title)) + '</h3><p>' + esc(L(p.agency)) +
        '</p><code>' + esc(p.grant) + '</code><p>' + esc(L(p.description)) + '</p>' + sourceLink(p.source) + '</li>';
    }).join("");
    var el = document.getElementById("project-list");
    if (!el) return;
    el.innerHTML = D.projects.map(function (p) {
      return '<li class="project-item">' +
        '<div class="period">' + esc(p.period) + "</div>" +
        "<div>" +
          '<h3 class="title"><span class="status-dot ' + (p.status === "active" ? "active" : "") + '" aria-hidden="true"></span>' + esc(L(p.title)) + "</h3>" +
          "<dl>" +
            "<dt>" + esc(t("funder")) + "</dt><dd>" + esc(L(p.funder)) + "</dd>" +
            "<dt>" + esc(t("role")) + "</dt><dd>" + esc(L(p.role)) + " · " + esc(t("status_" + p.status)) + "</dd>" +
          "</dl>" +
        "</div>" +
      "</li>";
    }).join("");
  };

  pages.news = function () {
    var el = document.getElementById("news-list");
    var cats = document.getElementById("news-cats");
    if (!el) return;
    var state = pages.news.state || (pages.news.state = { cat: "all" });
    var all = sortedNews();
    var catList = ["all"].concat(all.map(function (n) { return n.category; }).filter(function (c, i, a) { return a.indexOf(c) === i; }));
    if (cats) {
      cats.innerHTML = catList.map(function (c) {
        return '<button type="button" class="filter-btn" data-v="' + c + '" aria-pressed="' + (state.cat === c) + '">' + esc(c === "all" ? t("filter_all") : t("cat_" + c)) + "</button>";
      }).join("");
      cats.querySelectorAll(".filter-btn").forEach(function (b) {
        b.addEventListener("click", function () {
          state.cat = b.getAttribute("data-v");
          cats.querySelectorAll(".filter-btn").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
          draw();
        });
      });
    }
    function draw() {
      var rows = all.filter(function (n) { return state.cat === "all" || n.category === state.cat; });
      if (!rows.length) { el.innerHTML = '<p class="muted">' + esc(t("no_results")) + "</p>"; return; }
      var byYear = {};
      rows.forEach(function (n) { var y = n.date.slice(0, 4); (byYear[y] = byYear[y] || []).push(n); });
      el.innerHTML = Object.keys(byYear).sort(function (a, b) { return b - a; }).map(function (y) {
        return '<div class="pub-year-head"><h2 class="heading-sm num">' + y + "</h2></div>" +
          '<ul class="rule-list">' + byYear[y].map(newsItem).join("") + "</ul>";
      }).join("");
    }
    draw();
  };

  pages.contact = function () {
    var el = document.getElementById("contact-info");
    if (el) el.innerHTML =
      "<div>" +
        '<div class="item"><dt>' + esc(t("address")) + "</dt><dd>" + esc(L(D.lab.address)) + '<br><a class="link" href="' + esc(D.lab.mapUrl) + '" target="_blank" rel="noopener">' + esc(t("open_map")) + "</a></dd></div>" +
      "</div><div>" +
        '<div class="item"><dt>' + esc(t("email")) + '</dt><dd><a href="mailto:' + esc(D.lab.email) + '">' + esc(D.lab.email) + "</a></dd></div>" +
        '<div class="item"><dt>' + esc(t("phone")) + '</dt><dd><a href="tel:' + esc(D.lab.phone.replace(/-/g, "")) + '">' + esc(D.lab.phone) + "</a></dd></div>" +
        '<div class="item"><dt>' + esc(t("role_professor")) + '</dt><dd><a href="tel:' + esc(D.professor.phone.replace(/-/g, "")) + '">' + esc(D.professor.phone) + "</a></dd></div>" +
        '<div class="item"><dt>' + esc(t("office")) + "</dt><dd>" + esc(L(D.professor.office)) + "</dd></div>" +
      "</div>";
    var steps = document.getElementById("join-steps");
    if (steps) steps.innerHTML = D.i18n.join_steps.map(function (s) { return "<li><span>" + esc(L(s)) + "</span></li>"; }).join("");
  };

  /* ---------- 스크롤 리빌 (뷰포트 아래 요소에만 적용) ---------- */
  var io = null;
  function setupReveal() {
    var nodes = document.querySelectorAll("[data-reveal]:not(.reveal):not(.is-in)");
    if (!nodes.length) return;
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!("IntersectionObserver" in window) || reduce) { nodes.forEach(function (n) { n.classList.add("is-in"); }); return; }
    if (!io) io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        var el = e.target;
        var sib = Array.prototype.filter.call(el.parentNode.children, function (c) { return c.hasAttribute("data-reveal") && !c.classList.contains("is-in"); });
        var idx = Math.min(sib.indexOf(el), 5);
        el.style.transitionDelay = (idx > 0 ? idx * 60 : 0) + "ms";
        el.classList.add("is-in");
        io.unobserve(el);
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.1 });
    var vh = window.innerHeight;
    nodes.forEach(function (n) {
      var r = n.getBoundingClientRect();
      if (r.top < vh * 0.92) { n.classList.add("is-in"); return; } // 첫 화면은 즉시 보임
      n.classList.add("reveal");
      io.observe(n);
    });
  }

  /* ---------- 페이지 전환 폴백 (View Transitions 미지원 시) ---------- */
  function setupTransitions() {
    if ("onpageswap" in window) return; // 브라우저가 cross-document View Transitions 지원
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a[href]");
      if (!a || a.target === "_blank" || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
      var href = a.getAttribute("href");
      if (!href || href.charAt(0) === "#" || /^(mailto|tel|http)/.test(href)) return;
      if (href.indexOf("#") > -1 && href.split("#")[0] === currentFile()) return;
      e.preventDefault();
      document.documentElement.classList.add("is-leaving");
      setTimeout(function () { location.href = href; }, 150);
    });
    window.addEventListener("pageshow", function () { document.documentElement.classList.remove("is-leaving"); });
  }

  /* ---------- 실행 ---------- */
  function renderAll() {
    document.body.classList.remove("menu-open");
    document.documentElement.lang = lang;
    renderNav();
    renderFooter();
    applyI18n();
    var page = document.body.getAttribute("data-page");
    if (page && pages[page]) pages[page]();
    setupReveal();
    document.dispatchEvent(new CustomEvent("ailab:rendered", { detail: { lang: lang } }));
  }
  renderAll();
  setupTransitions();
  window.AILAB = { t: t, L: L, get lang() { return lang; }, setLang: setLang, render: renderAll };
})();
