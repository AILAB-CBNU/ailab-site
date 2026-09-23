(function () {
  "use strict";

  var LINK_KEYS = ["github", "linkedin", "website"];
  var LINK_NAMES = { github: "GitHub", linkedin: "LinkedIn", website: "개인 홈페이지" };
  var MAX_INPUT = 10 * 1024 * 1024;
  var MAX_OUTPUT = 2 * 1024 * 1024;

  function local(value) {
    return typeof value === "string" ? value : value && (value.ko || value.en) || "";
  }

  function escapeHtml(value) {
    return String(value || "").replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }

  function links(value) {
    var result = {};
    LINK_KEYS.forEach(function (key) { result[key] = value && typeof value[key] === "string" ? value[key] : ""; });
    return result;
  }

  function safePhoto(value) {
    var path = String(value || "");
    if (path.split("/").some(function (part) { return part === ".."; })) return "";
    return /^(?:\/people-photos\/[A-Za-z0-9_-]+\.png|\/?assets\/[A-Za-z0-9_./-]+)$/.test(path) ? path : "";
  }

  function photoPng(file, maximumDimension) {
    if (!file || !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      return Promise.reject(new Error("JPEG, PNG 또는 WebP 이미지 파일을 선택해 주세요."));
    }
    if (file.size > MAX_INPUT) return Promise.reject(new Error("사진은 10MB 이하로 선택해 주세요."));
    if (!file.size) return Promise.reject(new Error("비어 있는 이미지 파일은 등록할 수 없습니다."));
    return new Promise(function (resolve, reject) {
      var image = new Image();
      var objectUrl = URL.createObjectURL(file);
      image.onerror = function () {
        URL.revokeObjectURL(objectUrl);
        reject(new Error("이미지를 읽지 못했습니다. 다른 이미지 파일로 다시 시도해 주세요."));
      };
      image.onload = function () {
        URL.revokeObjectURL(objectUrl);
        if (!image.naturalWidth || !image.naturalHeight) { reject(new Error("이미지 크기를 확인할 수 없습니다.")); return; }
        var dimension = maximumDimension || 768;
        var scale = Math.min(1, dimension / image.naturalWidth, dimension / image.naturalHeight);
        var canvas = document.createElement("canvas");
        function encode(attempt) {
          try {
            canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
            canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
            var context = canvas.getContext("2d");
            if (!context) throw new Error("이 브라우저에서 이미지를 변환할 수 없습니다.");
            context.drawImage(image, 0, 0, canvas.width, canvas.height);
            canvas.toBlob(function (blob) {
              if (!blob) { reject(new Error("이미지를 변환하지 못했습니다. 다른 사진으로 다시 시도하세요.")); return; }
              if (blob.size <= MAX_OUTPUT) { resolve(blob); return; }
              if (attempt >= 4) { reject(new Error("변환한 사진이 2MB를 넘습니다. 더 작은 사진으로 다시 시도해 주세요.")); return; }
              scale *= 0.8;
              encode(attempt + 1);
            }, "image/png");
          } catch (error) { reject(error); }
        }
        encode(0);
      };
      image.src = objectUrl;
    });
  }

  function create(options) {
    var data = window.SITE_DATA || {};
    var people = [];
    function addPerson(person, group, role) {
      if (!person || !person.id || people.some(function (row) { return row.id === person.id; })) return;
      people.push({ id: person.id, name: local(person.name), role: role, group: group, photo: safePhoto(person.photo) });
    }
    addPerson(data.professor, "current", local(data.professor && data.professor.title) || "교수");
    (data.members || []).forEach(function (person) { addPerson(person, "current", local(person.year) || local(person.role)); });
    (data.alumni || []).forEach(function (person) { addPerson(person, "alumni", "Alumni · " + local(person.degree)); });

    var state = { selected: people[0] && people[0].id, profiles: {}, drafts: {}, ready: false, loading: false, epoch: 0 };
    var byId = function (id) { return people.find(function (person) { return person.id === id; }); };
    var node = function (id) { return document.getElementById(id); };
    var picker = node("profile-person-list");
    var details = node("profile-details");
    var search = node("profile-search");
    var group = node("profile-group");
    var message = node("people-manager-message");
    var refresh = node("refresh-people-profiles");
    var image = node("profile-photo-preview");
    var initial = node("profile-photo-initial");
    var fileInput = node("profile-photo-file");
    var photoDelete = node("delete-profile-photo");
    var save = node("save-profile-links");

    function profile(id) { return state.profiles[id] || { links: links(), photo: "" }; }

    function draft(id) {
      if (!state.drafts[id]) state.drafts[id] = {
        values: links(profile(id).links), dirty: false, revision: 0, saving: false, photoBusy: false,
        photoMessage: "", photoError: false, linkMessage: "", linkError: false
      };
      return state.drafts[id];
    }

    function anyBusy() {
      return Object.keys(state.drafts).some(function (id) { return state.drafts[id].saving || state.drafts[id].photoBusy; });
    }

    function status(target, text, error) {
      target.textContent = text;
      target.classList.toggle("is-error", !!error);
    }

    function errorMessage(error, action) {
      if (error.status === 401) { options.onUnauthorized(); return "로그인이 만료되었습니다."; }
      if (error.status === 404 || error.status === 405 || error.status === 501) {
        return "서버가 구성원 관리 기능을 지원하지 않거나 구성원 정보를 찾을 수 없습니다. 구성원 관리 업데이트 패키지를 적용하고 홈페이지 서버를 다시 실행하세요.";
      }
      if (error.status === 403) return "요청 권한을 확인하지 못했습니다. 홈페이지와 같은 주소의 관리자 페이지에서 다시 로그인하세요.";
      if (error.status === 413) return "파일 용량이 서버 제한을 넘었습니다. 더 작은 사진을 선택해 주세요.";
      if (error.status === 400 || error.status === 415) return action === "photo" ? "서버가 사진을 처리하지 못했습니다. JPEG, PNG 또는 WebP 파일로 다시 시도하세요." : "입력한 링크 주소를 확인해 주세요. GitHub와 LinkedIn은 해당 서비스의 주소여야 합니다.";
      if (error.status) return "서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.";
      return error.message && error.message !== "Failed to fetch" ? error.message : "서버에 연결하지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.";
    }

    function renderPicker() {
      var query = search.value.trim().toLowerCase();
      var rows = people.filter(function (person) {
        return (group.value === "all" || person.group === group.value) && (!query || (person.name + " " + person.role).toLowerCase().includes(query));
      });
      node("profile-result-count").textContent = rows.length + "명";
      picker.innerHTML = rows.map(function (person) {
        return '<button type="button" data-profile-id="' + escapeHtml(person.id) + '" aria-pressed="' + (person.id === state.selected) + '"><strong>' + escapeHtml(person.name) + '</strong><span>' + escapeHtml(person.role) + '</span></button>';
      }).join("") || '<p class="profile-help">검색 결과가 없습니다.</p>';
    }

    function renderDetails() {
      var person = byId(state.selected);
      details.hidden = !person;
      refresh.disabled = state.loading || anyBusy();
      if (!person) return;
      var edit = draft(person.id);
      var saved = profile(person.id);
      node("profile-person-name").textContent = person.name;
      node("profile-person-role").textContent = person.role;
      initial.textContent = Array.from(person.name)[0] || "?";
      var src = safePhoto(saved.photo) || person.photo;
      image.hidden = !src || image.dataset.failedSrc === src;
      initial.hidden = !image.hidden;
      image.alt = person.name + " 프로필 사진";
      if (src && image.getAttribute("src") !== src) image.src = src;
      if (!src) image.removeAttribute("src");
      fileInput.disabled = !state.ready || edit.photoBusy;
      photoDelete.disabled = !state.ready || edit.photoBusy || !safePhoto(saved.photo);
      photoDelete.textContent = edit.photoBusy ? "처리 중…" : "등록한 사진 삭제";
      status(node("profile-photo-status"), edit.photoMessage, edit.photoError);
      LINK_KEYS.forEach(function (key) {
        var input = node("profile-" + key);
        if (input.value !== edit.values[key]) input.value = edit.values[key];
        input.disabled = !state.ready;
      });
      save.disabled = !state.ready || !edit.dirty || edit.saving;
      save.textContent = edit.saving ? "저장 중…" : "링크 저장";
      status(node("profile-links-status"), edit.linkMessage || (edit.dirty ? "저장되지 않은 링크 변경사항" : ""), edit.linkError);
    }

    function load() {
      if (state.loading || anyBusy()) return;
      var epoch = state.epoch;
      state.loading = true;
      state.ready = false;
      status(message, "구성원 정보를 불러오는 중입니다.");
      renderDetails();
      options.api("/api/people-profiles", { cache: "no-store" }).then(function (result) {
        if (epoch !== state.epoch) return;
        if (!result || result.version !== 1 || !result.profiles || Array.isArray(result.profiles) || typeof result.profiles !== "object") throw new Error("구성원 정보 응답을 확인할 수 없습니다. 서버 업데이트를 확인해 주세요.");
        state.profiles = result.profiles;
        Object.keys(state.drafts).forEach(function (id) {
          if (!state.drafts[id].dirty) state.drafts[id].values = links(profile(id).links);
        });
        state.ready = true;
        status(message, "교수·현재 구성원·Alumni " + people.length + "명의 사진과 링크를 관리할 수 있습니다.");
      }).catch(function (error) {
        if (epoch === state.epoch) status(message, errorMessage(error, "load"), true);
      }).finally(function () {
        if (epoch === state.epoch) { state.loading = false; renderDetails(); }
      });
    }

    function applyPhoto(id, operation) {
      if (!state.ready || draft(id).photoBusy) return;
      var edit = draft(id);
      var epoch = state.epoch;
      edit.photoBusy = true;
      edit.photoError = false;
      edit.photoMessage = "사진을 처리하는 중입니다.";
      renderDetails();
      operation().then(function (result) {
        if (epoch !== state.epoch) return;
        if (!result || result.ok !== true || !result.profile || typeof result.profile.photo !== "string") throw new Error("사진 저장 결과를 확인하지 못했습니다. 새로고침 후 사진을 확인해 주세요.");
        state.profiles[id] = { links: links(profile(id).links), photo: result.profile.photo };
        edit.photoMessage = result.profile.photo ? "사진이 저장되었습니다." : "등록한 사진을 삭제하고 기본 표시로 되돌렸습니다.";
      }).catch(function (error) {
        if (epoch === state.epoch) { edit.photoMessage = errorMessage(error, "photo"); edit.photoError = true; }
      }).finally(function () {
        if (epoch !== state.epoch) return;
        edit.photoBusy = false;
        renderDetails();
      });
    }

    function checkedLinks(edit) {
      var result = {};
      LINK_KEYS.forEach(function (key) {
        var value = edit.values[key].trim();
        var input = node("profile-" + key);
        input.setCustomValidity("");
        if (value) {
          var valid = false;
          try {
            var url = new URL(value);
            var host = url.hostname.toLowerCase();
            valid = value.length <= 2048 && /^https?:\/\//i.test(value) && !/[\s\\\x00-\x1f\x7f]/.test(value) && /^https?:$/.test(url.protocol) && !url.username && !url.password && !!host;
            if (key === "github") valid = valid && ["github.com", "www.github.com"].includes(host);
            if (key === "linkedin") valid = valid && (host === "linkedin.com" || host.endsWith(".linkedin.com"));
          } catch (error) { valid = false; }
          if (!valid) {
            var text = LINK_NAMES[key] + " 주소를 확인해 주세요. " + (key === "website" ? "http:// 또는 https://로 시작하는 전체 주소를 입력하세요." : "해당 서비스의 https:// 주소를 입력하세요.");
            input.setCustomValidity(text);
            input.reportValidity();
            throw new Error(text);
          }
        }
        result[key] = value;
      });
      return result;
    }

    picker.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-profile-id]");
      if (!button || !byId(button.dataset.profileId)) return;
      state.selected = button.dataset.profileId;
      fileInput.value = "";
      LINK_KEYS.forEach(function (key) { node("profile-" + key).setCustomValidity(""); });
      renderPicker();
      renderDetails();
    });
    search.addEventListener("input", renderPicker);
    group.addEventListener("change", renderPicker);
    refresh.addEventListener("click", load);
    image.addEventListener("error", function () { image.dataset.failedSrc = image.getAttribute("src"); image.hidden = true; initial.hidden = false; });

    fileInput.addEventListener("change", function () {
      var file = fileInput.files && fileInput.files[0];
      var id = state.selected;
      var epoch = state.epoch;
      fileInput.value = "";
      if (!file || !id) return;
      applyPhoto(id, function () {
        return photoPng(file).then(function (blob) {
          if (epoch !== state.epoch) return null;
          return options.api("/api/admin/people/" + encodeURIComponent(id) + "/photo", { method: "POST", headers: { "Content-Type": "image/png" }, body: blob });
        });
      });
    });
    photoDelete.addEventListener("click", function () {
      var id = state.selected;
      if (!id || !profile(id).photo) return;
      applyPhoto(id, function () { return options.api("/api/admin/people/" + encodeURIComponent(id) + "/photo", { method: "DELETE" }); });
    });

    LINK_KEYS.forEach(function (key) {
      node("profile-" + key).addEventListener("input", function () {
        if (!state.selected) return;
        var edit = draft(state.selected);
        edit.values[key] = this.value;
        edit.dirty = true;
        edit.revision += 1;
        edit.linkMessage = "";
        edit.linkError = false;
        this.setCustomValidity("");
        renderDetails();
      });
    });

    node("profile-links-form").addEventListener("submit", function (event) {
      event.preventDefault();
      var id = state.selected;
      if (!id || !state.ready) return;
      var edit = draft(id);
      if (edit.saving || !edit.dirty) return;
      var values;
      try { values = checkedLinks(edit); }
      catch (error) { edit.linkMessage = error.message; edit.linkError = true; renderDetails(); return; }
      var revision = edit.revision;
      var epoch = state.epoch;
      edit.saving = true;
      edit.linkError = false;
      renderDetails();
      options.api("/api/admin/people/" + encodeURIComponent(id), { method: "PUT", body: JSON.stringify({ links: values }) }).then(function (result) {
        if (epoch !== state.epoch) return;
        if (!result || result.ok !== true || !result.profile || !result.profile.links) throw new Error("링크 저장 결과를 확인하지 못했습니다. 새로고침 후 확인해 주세요.");
        state.profiles[id] = { photo: profile(id).photo || "", links: links(result.profile.links) };
        if (revision === edit.revision) {
          edit.values = links(result.profile.links);
          edit.dirty = false;
          edit.linkMessage = "링크가 저장되었습니다.";
        } else edit.linkMessage = "이전 입력은 저장되었습니다. 추가 변경사항을 저장해 주세요.";
      }).catch(function (error) {
        if (epoch === state.epoch) { edit.linkMessage = errorMessage(error, "links"); edit.linkError = true; }
      }).finally(function () {
        if (epoch !== state.epoch) return;
        edit.saving = false;
        renderDetails();
      });
    });

    return {
      open: function () { renderPicker(); renderDetails(); if (!state.ready) load(); },
      reset: function () {
        state.epoch += 1;
        state.profiles = {};
        state.drafts = {};
        state.ready = false;
        state.loading = false;
        fileInput.value = "";
      }
    };
  }

  window.AILAB_ADMIN_PEOPLE = { create: create, photoPng: photoPng };
})();
