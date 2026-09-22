/* Lightweight text/link overrides and visual editor bridge. */
(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var editorMode = params.get("cms-edit") === "1";
  var pageFile = location.pathname.split("/").pop() || "index.html";
  var overrides = { version: 1, global: { ko: {}, en: {} }, pages: {} };
  var scheduled = false;

  function language() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function mapFor(scope) {
    var lang = language();
    if (scope === "global") return (overrides.global && overrides.global[lang]) || {};
    var page = overrides.pages && overrides.pages[pageFile];
    return (page && page[lang]) || {};
  }

  function roots() {
    return [
      { node: document.getElementById("site-nav"), scope: "global", region: "header" },
      { node: document.querySelector("main"), scope: "page", region: "page" },
      { node: document.getElementById("site-footer"), scope: "global", region: "footer" }
    ].filter(function (item) { return item.node; });
  }

  function siblingIndex(element) {
    var tag = element.tagName;
    var siblings = Array.prototype.filter.call(element.parentElement ? element.parentElement.children : [], function (child) {
      return child.tagName === tag && !child.hasAttribute("data-cms-node");
    });
    return Math.max(0, siblings.indexOf(element));
  }

  function elementPath(element, root) {
    if (root.id === "site-nav") {
      var anchor = element.closest && element.closest("a[href]");
      if (anchor && root.contains(anchor)) {
        var href = anchor.getAttribute("data-cms-original-href") || anchor.getAttribute("href") || "link";
        var base = anchor.classList.contains("gn-brand") ? "brand" : "nav[" + href + "]";
        if (element === anchor) return base;
        if (element.classList.contains("sub")) return base + "/sub";
        return base + "/" + element.tagName.toLowerCase() + "[" + siblingIndex(element) + "]";
      }
    }
    var parts = [];
    var current = element;
    while (current && current !== root) {
      if (current.id) {
        parts.unshift("#" + current.id);
        break;
      }
      parts.unshift(current.tagName.toLowerCase() + "[" + siblingIndex(current) + "]");
      current = current.parentElement;
    }
    return parts.join("/") || "root";
  }

  function ignored(textNode) {
    var parent = textNode.parentElement;
    if (!parent || !textNode.nodeValue || !textNode.nodeValue.trim()) return true;
    if (/^(SCRIPT|STYLE|NOSCRIPT|SVG|PATH|TEXTAREA|INPUT|SELECT|OPTION)$/.test(parent.tagName)) return true;
    if (parent.closest("[data-cms-ignore], [data-cms-node]")) return true;
    return false;
  }

  function splitWhitespace(raw) {
    var leading = (raw.match(/^\s*/) || [""])[0];
    var trailing = (raw.match(/\s*$/) || [""])[0];
    return { leading: leading, value: raw.slice(leading.length, raw.length - trailing.length), trailing: trailing };
  }

  function wrapText(rootInfo) {
    var walker = document.createTreeWalker(rootInfo.node, NodeFilter.SHOW_TEXT);
    var candidates = [];
    var node;
    while ((node = walker.nextNode())) {
      if (!ignored(node)) candidates.push(node);
    }
    var map = mapFor(rootInfo.scope);
    candidates.forEach(function (textNode) {
      if (!textNode.parentElement || textNode.parentElement.closest("[data-cms-node]")) return;
      var parent = textNode.parentElement;
      var textNodes = Array.prototype.filter.call(parent.childNodes, function (child) {
        return child.nodeType === Node.TEXT_NODE && child.nodeValue && child.nodeValue.trim();
      });
      var key = elementPath(parent, rootInfo.node) + "/text[" + Math.max(0, textNodes.indexOf(textNode)) + "]";
      var pieces = splitWhitespace(textNode.nodeValue);
      var span = document.createElement("span");
      span.setAttribute("data-cms-node", "text");
      span.setAttribute("data-cms-scope", rootInfo.scope);
      span.setAttribute("data-cms-region", rootInfo.region);
      span.setAttribute("data-cms-key", key);
      span.setAttribute("data-cms-original", pieces.value);
      span.textContent = Object.prototype.hasOwnProperty.call(map, key) ? map[key] : pieces.value;
      var fragment = document.createDocumentFragment();
      if (pieces.leading) fragment.appendChild(document.createTextNode(pieces.leading));
      fragment.appendChild(span);
      if (pieces.trailing) fragment.appendChild(document.createTextNode(pieces.trailing));
      textNode.parentNode.replaceChild(fragment, textNode);
    });
  }

  function safeHref(value) {
    return /^(?:https?:\/\/|mailto:|tel:|[#/?]|[A-Za-z0-9_.-]+(?:[/?#]|$))/.test(value || "");
  }

  function applyAttributes(rootInfo) {
    var map = mapFor(rootInfo.scope);
    rootInfo.node.querySelectorAll("a[href]").forEach(function (anchor) {
      var key = elementPath(anchor, rootInfo.node) + "@href";
      anchor.setAttribute("data-cms-link-key", key);
      anchor.setAttribute("data-cms-scope", rootInfo.scope);
      anchor.setAttribute("data-cms-region", rootInfo.region);
      if (!anchor.hasAttribute("data-cms-original-href")) anchor.setAttribute("data-cms-original-href", anchor.getAttribute("href"));
      var value = Object.prototype.hasOwnProperty.call(map, key) ? map[key] : anchor.getAttribute("data-cms-original-href");
      if (safeHref(value)) anchor.setAttribute("href", value);
    });
    rootInfo.node.querySelectorAll("[placeholder]").forEach(function (input) {
      var key = elementPath(input, rootInfo.node) + "@placeholder";
      input.setAttribute("data-cms-placeholder-key", key);
      input.setAttribute("data-cms-scope", rootInfo.scope);
      input.setAttribute("data-cms-region", rootInfo.region);
      if (!input.hasAttribute("data-cms-original-placeholder")) input.setAttribute("data-cms-original-placeholder", input.getAttribute("placeholder"));
      if (Object.prototype.hasOwnProperty.call(map, key)) input.setAttribute("placeholder", map[key]);
    });
  }

  function applyExisting() {
    document.querySelectorAll("[data-cms-node='text']").forEach(function (span) {
      var map = mapFor(span.getAttribute("data-cms-scope"));
      var key = span.getAttribute("data-cms-key");
      var value = Object.prototype.hasOwnProperty.call(map, key) ? map[key] : span.getAttribute("data-cms-original");
      if (span.textContent !== value) span.textContent = value;
    });
    roots().forEach(applyAttributes);
  }

  function inventory() {
    var items = [];
    document.querySelectorAll("[data-cms-node='text']").forEach(function (span) {
      items.push({
        scope: span.getAttribute("data-cms-scope"),
        region: span.getAttribute("data-cms-region"),
        key: span.getAttribute("data-cms-key"),
        kind: "text",
        tag: span.parentElement ? span.parentElement.tagName.toLowerCase() : "text",
        value: span.textContent || "",
        original: span.getAttribute("data-cms-original") || ""
      });
    });
    document.querySelectorAll("[data-cms-link-key]").forEach(function (anchor) {
      items.push({
        scope: anchor.getAttribute("data-cms-scope"),
        region: anchor.getAttribute("data-cms-region"),
        key: anchor.getAttribute("data-cms-link-key"),
        kind: "link",
        tag: "a",
        value: anchor.getAttribute("href") || "",
        original: anchor.getAttribute("data-cms-original-href") || "",
        context: (anchor.textContent || "").trim()
      });
    });
    document.querySelectorAll("[data-cms-placeholder-key]").forEach(function (input) {
      items.push({
        scope: input.getAttribute("data-cms-scope"),
        region: input.getAttribute("data-cms-region"),
        key: input.getAttribute("data-cms-placeholder-key"),
        kind: "placeholder",
        tag: input.tagName.toLowerCase(),
        value: input.getAttribute("placeholder") || "",
        original: input.getAttribute("data-cms-original-placeholder") || ""
      });
    });
    return items;
  }

  function postInventory() {
    if (!editorMode || window.parent === window) return;
    window.parent.postMessage({ type: "ailab-cms-ready", page: pageFile, lang: language(), items: inventory() }, location.origin);
  }

  function process() {
    scheduled = false;
    roots().forEach(function (rootInfo) {
      wrapText(rootInfo);
      applyAttributes(rootInfo);
    });
    applyExisting();
    postInventory();
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    window.setTimeout(process, 60);
  }

  function findField(scope, key) {
    return document.querySelector('[data-cms-scope="' + scope + '"][data-cms-key="' + CSS.escape(key) + '"]') ||
      document.querySelector('[data-cms-scope="' + scope + '"][data-cms-link-key="' + CSS.escape(key) + '"]') ||
      document.querySelector('[data-cms-scope="' + scope + '"][data-cms-placeholder-key="' + CSS.escape(key) + '"]');
  }

  window.addEventListener("message", function (event) {
    if (!editorMode || event.origin !== location.origin || !event.data) return;
    if (event.data.type === "ailab-cms-preview") {
      var scope = event.data.scope === "global" ? "global" : "page";
      var map = mapFor(scope);
      map[event.data.key] = String(event.data.value == null ? "" : event.data.value);
      applyExisting();
      roots().forEach(applyAttributes);
    }
    if (event.data.type === "ailab-cms-focus") {
      var target = findField(event.data.scope, event.data.key);
      if (target) {
        document.querySelectorAll(".cms-focus").forEach(function (node) { node.classList.remove("cms-focus"); });
        target.classList.add("cms-focus");
        target.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  });

  if (editorMode) {
    var style = document.createElement("style");
    style.textContent = ".cms-focus{outline:3px solid #0071e3!important;outline-offset:4px!important;border-radius:3px}";
    document.head.appendChild(style);
  }

  fetch("/api/content-overrides", { credentials: "same-origin", cache: "no-store" })
    .then(function (response) { return response.ok ? response.json() : overrides; })
    .then(function (value) { overrides = value || overrides; schedule(); })
    .catch(schedule);

  document.addEventListener("ailab:rendered", schedule);
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  schedule();
})();
