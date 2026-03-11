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
    document.body.classList.add("lv-page-loading");
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
    const feedback = panel.querySelector("#lv-version-feedback");

    let pendingPublishUrl = "";
    let submitting = false;

    function setButtonLoading(button, loading, label) {
      if (!button) {
        return;
      }
      if (loading) {
        if (!button.dataset.lvOriginalLabel) {
          button.dataset.lvOriginalLabel = button.textContent.trim();
        }
        button.classList.add("is-loading");
        button.disabled = true;
        if (label) {
          button.textContent = label;
        }
        return;
      }

      button.classList.remove("is-loading");
      button.disabled = false;
      if (button.dataset.lvOriginalLabel) {
        button.textContent = button.dataset.lvOriginalLabel;
      }
    }

    function toggleDisabled(elements, disabled) {
      (elements || []).forEach(function (element) {
        if (!element) {
          return;
        }
        element.disabled = !!disabled;
      });
    }

    function clearFeedback() {
      if (!feedback) {
        return;
      }
      feedback.hidden = true;
      feedback.textContent = "";
      feedback.classList.remove(
        "lv-feedback-banner--error",
        "lv-feedback-banner--success",
        "lv-feedback-banner--info",
        "lv-feedback-banner--loading"
      );
    }

    function setFeedback(kind, message) {
      if (!feedback) {
        return;
      }
      feedback.hidden = false;
      feedback.textContent = message || "";
      feedback.classList.remove(
        "lv-feedback-banner--error",
        "lv-feedback-banner--success",
        "lv-feedback-banner--info",
        "lv-feedback-banner--loading"
      );
      feedback.classList.add("lv-feedback-banner--" + kind);
    }

    function setSubmittingState(isSubmitting) {
      submitting = isSubmitting;
      panel.classList.toggle("lv-version-pipeline--submitting", isSubmitting);
      toggleDisabled(
        [addBtn, addCancelBtn, publishCancelBtn, versionNameInput, changelogInput],
        isSubmitting
      );
    }

    function closeAddModal() {
      if (submitting) {
        return;
      }
      if (addModal) {
        addModal.hidden = true;
      }
    }

    function closePublishModal() {
      if (submitting) {
        return;
      }
      if (publishModal) {
        publishModal.hidden = true;
      }
      pendingPublishUrl = "";
    }

    if (addBtn && addModal) {
      addBtn.addEventListener("click", function () {
        clearFeedback();
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
        if (submitting) {
          return;
        }
        const createUrl = panel.dataset.createUrl;
        const versionName = versionNameInput ? versionNameInput.value.trim() : "";
        const changelog = changelogInput ? changelogInput.value.trim() : "";
        if (!createUrl) {
          setFeedback("error", "Nao foi possivel identificar a rota para criar a versao.");
          return;
        }
        if (!versionName) {
          setFeedback("error", "Informe o nome da nova versao.");
          if (versionNameInput) {
            versionNameInput.focus();
          }
          return;
        }
        if (!changelog) {
          setFeedback("error", "Informe o changelog da nova versao.");
          if (changelogInput) {
            changelogInput.focus();
          }
          return;
        }
        setFeedback("loading", "Criando nova versao em rascunho...");
        setButtonLoading(addConfirmBtn, true, "Criando...");
        setSubmittingState(true);
        submitPost(createUrl, { version: versionName, changelog: changelog });
      });
    }

    panel.querySelectorAll(".lv-publish-version-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (submitting) {
          return;
        }
        clearFeedback();
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
        if (submitting || !pendingPublishUrl) {
          return;
        }
        setFeedback("loading", "Publicando versao e consolidando status...");
        setButtonLoading(publishConfirmBtn, true, "Publicando...");
        setSubmittingState(true);
        submitPost(pendingPublishUrl, {});
      });
    }

    if (addModal) {
      addModal.addEventListener("click", function (event) {
        if (event.target === addModal) {
          closeAddModal();
        }
      });
    }

    if (publishModal) {
      publishModal.addEventListener("click", function (event) {
        if (event.target === publishModal) {
          closePublishModal();
        }
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }
      if (addModal && !addModal.hidden) {
        closeAddModal();
      }
      if (publishModal && !publishModal.hidden) {
        closePublishModal();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", bootVersionPipeline);
})();
