(function () {
  function getCookie(name) {
    const cookies = document.cookie ? document.cookie.split(";") : [];
    for (const cookieRaw of cookies) {
      const cookie = cookieRaw.trim();
      if (cookie.startsWith(name + "=")) {
        return decodeURIComponent(cookie.slice(name.length + 1));
      }
    }
    return "";
  }

  function getCsrfToken() {
    const fromCookie = getCookie("csrftoken");
    if (fromCookie) {
      return fromCookie;
    }

    const fromFormInput = document.querySelector(
      'form input[name="csrfmiddlewaretoken"]'
    );
    if (fromFormInput && fromFormInput.value) {
      return fromFormInput.value;
    }

    const fromAnyInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
    if (fromAnyInput && fromAnyInput.value) {
      return fromAnyInput.value;
    }

    return "";
  }

  function submitPost(url, fields) {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = url;
    form.style.display = "none";

    const csrfToken = getCsrfToken();
    if (csrfToken) {
      const csrfInput = document.createElement("input");
      csrfInput.type = "hidden";
      csrfInput.name = "csrfmiddlewaretoken";
      csrfInput.value = csrfToken;
      form.appendChild(csrfInput);
    }

    Object.entries(fields || {}).forEach(([name, value]) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.appendChild(input);
    });

    document.body.appendChild(form);
    form.submit();
  }

  function bootVersionPipeline() {
    const panel = document.querySelector(".lv-version-pipeline");
    if (!panel) {
      return;
    }

    const addModal = panel.querySelector("#lv-add-version-modal");
    const publishModal = panel.querySelector("#lv-publish-version-modal");
    const addBtn = panel.querySelector(".lv-add-version-btn");
    const addConfirmBtn = panel.querySelector("#lv-confirm-add-version");
    const addCancelBtn = panel.querySelector("#lv-cancel-add-version");
    const publishConfirmBtn = panel.querySelector("#lv-confirm-publish-version");
    const publishCancelBtn = panel.querySelector("#lv-cancel-publish-version");
    const publishMessage = panel.querySelector("#lv-publish-version-message");
    const versionNameInput = panel.querySelector("#lv-new-version-name");
    const changelogInput = panel.querySelector("#lv-new-version-changelog");

    let pendingPublishUrl = "";

    function closeAddModal() {
      if (addModal) {
        addModal.hidden = true;
      }
    }

    function closePublishModal() {
      if (publishModal) {
        publishModal.hidden = true;
      }
      pendingPublishUrl = "";
    }

    if (addBtn && addModal) {
      addBtn.addEventListener("click", function () {
        addModal.hidden = false;
        if (versionNameInput) {
          versionNameInput.focus();
        }
      });
    }

    if (addCancelBtn) {
      addCancelBtn.addEventListener("click", closeAddModal);
    }

    if (addConfirmBtn) {
      addConfirmBtn.addEventListener("click", function () {
        const createUrl = panel.dataset.createUrl;
        const versionName = versionNameInput ? versionNameInput.value.trim() : "";
        const changelog = changelogInput ? changelogInput.value.trim() : "";
        if (!createUrl) {
          return;
        }
        if (!versionName) {
          window.alert("Informe o nome da nova versao.");
          return;
        }
        if (!changelog) {
          window.alert("Informe o changelog da nova versao.");
          return;
        }
        submitPost(createUrl, { version: versionName, changelog: changelog });
      });
    }

    panel.querySelectorAll(".lv-publish-version-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        pendingPublishUrl = btn.dataset.publishUrl || "";
        const versionLabel = btn.dataset.versionLabel || "esta versao";
        if (publishMessage) {
          publishMessage.textContent =
            `Deseja publicar a versao "${versionLabel}" agora?`;
        }
        if (publishModal) {
          publishModal.hidden = false;
        }
      });
    });

    if (publishCancelBtn) {
      publishCancelBtn.addEventListener("click", closePublishModal);
    }

    if (publishConfirmBtn) {
      publishConfirmBtn.addEventListener("click", function () {
        if (!pendingPublishUrl) {
          return;
        }
        submitPost(pendingPublishUrl, {});
      });
    }
  }

  document.addEventListener("DOMContentLoaded", bootVersionPipeline);
})();
