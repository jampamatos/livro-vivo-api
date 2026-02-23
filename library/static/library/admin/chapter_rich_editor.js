(function () {
  'use strict';

  function wrapEditor(textarea) {
    if (!textarea || textarea.dataset.richEditorReady === '1') {
      return;
    }

    var wrapper = document.createElement('div');
    wrapper.className = 'lv-rich-editor';

    var toolbar = document.createElement('div');
    toolbar.className = 'lv-rich-editor__toolbar';
    toolbar.setAttribute('role', 'toolbar');
    toolbar.setAttribute('aria-label', 'Chapter rich text toolbar');

    var actions = [
      { label: 'P', cmd: 'formatBlock', value: 'P', title: 'Paragraph' },
      { label: 'H2', cmd: 'formatBlock', value: 'H2', title: 'Heading 2' },
      { label: 'H3', cmd: 'formatBlock', value: 'H3', title: 'Heading 3' },
      { label: 'B', cmd: 'bold', title: 'Bold' },
      { label: 'I', cmd: 'italic', title: 'Italic' },
      { label: 'U', cmd: 'underline', title: 'Underline' },
      { label: 'UL', cmd: 'insertUnorderedList', title: 'Bulleted list' },
      { label: 'OL', cmd: 'insertOrderedList', title: 'Numbered list' },
      { label: 'Link', cmd: 'createLink', title: 'Insert link' },
      { label: 'Clear', cmd: 'removeFormat', title: 'Clear formatting' }
    ];

    actions.forEach(function (action) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'button lv-rich-editor__button';
      button.textContent = action.label;
      button.setAttribute('title', action.title);
      button.dataset.cmd = action.cmd;
      if (action.value) {
        button.dataset.value = action.value;
      }
      toolbar.appendChild(button);
    });

    var editor = document.createElement('div');
    editor.className = 'lv-rich-editor__surface';
    editor.contentEditable = 'true';
    editor.setAttribute('role', 'textbox');
    editor.setAttribute('aria-multiline', 'true');
    editor.setAttribute('aria-label', 'Chapter rich text content');
    editor.innerHTML = textarea.value || '';
    try {
      document.execCommand('defaultParagraphSeparator', false, 'p');
    } catch (error) {
      // browsers sem suporte mantêm comportamento padrão
    }

    wrapper.appendChild(toolbar);
    wrapper.appendChild(editor);
    textarea.parentNode.insertBefore(wrapper, textarea);
    textarea.classList.add('lv-rich-editor__source');

    function syncToTextarea() {
      textarea.value = editor.innerHTML.trim();
    }

    toolbar.addEventListener('click', function (event) {
      var target = event.target;
      if (!(target instanceof HTMLButtonElement)) {
        return;
      }

      event.preventDefault();
      editor.focus();

      var cmd = target.dataset.cmd;
      if (!cmd) {
        return;
      }

      if (cmd === 'createLink') {
        var href = window.prompt('URL do link (https://...)');
        if (!href) {
          return;
        }
        document.execCommand('createLink', false, href);
      } else if (cmd === 'formatBlock' && target.dataset.value) {
        var block = target.dataset.value.toLowerCase();
        if (!document.execCommand('formatBlock', false, block)) {
          document.execCommand('formatBlock', false, '<' + block + '>');
        }
      } else if (target.dataset.value) {
        document.execCommand(cmd, false, target.dataset.value);
      } else {
        document.execCommand(cmd, false, null);
      }

      syncToTextarea();
    });

    editor.addEventListener('input', syncToTextarea);
    editor.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        document.execCommand('insertParagraph', false, null);
        syncToTextarea();
      }
    });
    var form = textarea.closest('form');
    if (form) {
      form.addEventListener('submit', syncToTextarea);
    }

    textarea.dataset.richEditorReady = '1';
  }

  function initEditors(root) {
    var scope = root || document;
    var textareas = scope.querySelectorAll('textarea.js-rich-chapter-editor-source');
    textareas.forEach(wrapEditor);
  }

  document.addEventListener('DOMContentLoaded', function () {
    initEditors(document);

    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (!(node instanceof HTMLElement)) {
            return;
          }
          if (node.matches && node.matches('textarea.js-rich-chapter-editor-source')) {
            wrapEditor(node);
            return;
          }
          initEditors(node);
        });
      });
    });

    observer.observe(document.body, { childList: true, subtree: true });
  });
})();
