(function () {
  function readState() {
    var node = document.getElementById("lv-legal-document-version-admin-state");
    if (!node) {
      return null;
    }

    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  }

  function buildMessage(activeDocument) {
    return (
      "Ja existe uma versao ativa para " +
      activeDocument.document_type_label +
      ": " +
      activeDocument.label +
      ". Se voce continuar, ela sera desativada automaticamente. Deseja prosseguir?"
    );
  }

  function initialize() {
    var state = readState();
    var form = document.getElementById("legaldocumentversion_form");
    var documentTypeField = document.getElementById("id_document_type");
    var isActiveField = document.getElementById("id_is_active");
    var inlineWarning = document.getElementById("lv-legal-document-rollover-warning");

    if (!state || !form || !documentTypeField || !isActiveField || !inlineWarning) {
      return;
    }

    function resolveConflictingActiveDocument() {
      if (!isActiveField.checked) {
        return null;
      }

      var selectedType = documentTypeField.value;
      if (!selectedType) {
        return null;
      }

      var activeDocument = (state.activeByType || {})[selectedType];
      if (!activeDocument) {
        return null;
      }

      if (String(activeDocument.id) === String(state.currentDocumentId || "")) {
        return null;
      }

      return activeDocument;
    }

    function refreshInlineWarning() {
      var activeDocument = resolveConflictingActiveDocument();
      if (!activeDocument) {
        inlineWarning.hidden = true;
        inlineWarning.textContent = "";
        return;
      }

      inlineWarning.hidden = false;
      inlineWarning.textContent =
        "Atencao: ao salvar esta versao como ativa, a versao atualmente ativa deste tipo sera desativada: " +
        activeDocument.label +
        ".";
    }

    documentTypeField.addEventListener("change", refreshInlineWarning);
    isActiveField.addEventListener("change", refreshInlineWarning);
    refreshInlineWarning();

    form.addEventListener("submit", function (event) {
      var activeDocument = resolveConflictingActiveDocument();
      if (!activeDocument) {
        return;
      }

      if (!window.confirm(buildMessage(activeDocument))) {
        event.preventDefault();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", initialize);
})();
