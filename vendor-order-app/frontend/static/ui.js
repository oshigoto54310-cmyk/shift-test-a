/* 画面部品ヘルパ。
   - XSS対策: 文字列は必ず esc() を通してから innerHTML に入れる。
   - 状態は色だけで判別させず、アイコン＋文字を必ず併記する。
*/
(function (global) {
  'use strict';

  function esc(v) {
    if (v === null || v === undefined) return '';
    return String(v)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* ステータス → 色・アイコン。色だけに頼らないよう必ずラベルと併記する。 */
  const STATUS_STYLE = {
    DRAFT:            { cls: 'neutral', icon: '✎' },
    PLANNED:          { cls: 'neutral', icon: '🗒' },
    CONFIRMED:        { cls: 'primary', icon: '✔' },
    VENDOR_PENDING:   { cls: 'warn',    icon: '⏳' },
    VENDOR_ACK:       { cls: 'info',    icon: '👁' },
    PARTIAL:          { cls: 'warn',    icon: '◐' },
    SHORTAGE:         { cls: 'alert',   icon: '✖' },
    SUBSTITUTE:       { cls: 'info',    icon: '⇄' },
    DELIVERED:        { cls: 'ok',      icon: '📦' },
    CHANGE_REQUESTED: { cls: 'warn',    icon: '📝' },
    CHANGE_APPROVED:  { cls: 'ok',      icon: '☑' },
    CHANGE_REJECTED:  { cls: 'alert',   icon: '⊘' },
    CANCELLED:        { cls: 'neutral', icon: '⊗' },
    PENDING:          { cls: 'warn',    icon: '⏳' },
    APPROVED:         { cls: 'ok',      icon: '☑' },
    REJECTED:         { cls: 'alert',   icon: '⊘' },
    FULL:             { cls: 'ok',      icon: '✔' },
    CHECKING:         { cls: 'neutral', icon: '…' },
    CONSULT:          { cls: 'info',    icon: '☎' },
  };

  function badge(code, label) {
    const s = STATUS_STYLE[code] || { cls: 'neutral', icon: '•' };
    return '<span class="badge ' + s.cls + '"><span class="badge-icon" aria-hidden="true">' +
      s.icon + '</span>' + esc(label || code) + '</span>';
  }

  function fmtDate(v) {
    if (!v) return '';
    const d = new Date(v.length <= 10 ? v + 'T00:00:00' : v);
    if (isNaN(d)) return esc(v);
    return d.getFullYear() + '/' + pad(d.getMonth() + 1) + '/' + pad(d.getDate());
  }

  function fmtDateTime(v) {
    if (!v) return '';
    // サーバーはUTCのnaive datetimeを返すため、UTCとして解釈して日本時間で表示する
    const iso = v.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(v) ? v : v + 'Z';
    const d = new Date(iso);
    if (isNaN(d)) return esc(v);
    return d.toLocaleString('ja-JP', {
      timeZone: 'Asia/Tokyo', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  function todayStr(offsetDays) {
    const d = new Date();
    d.setDate(d.getDate() + (offsetDays || 0));
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function deadlineChip(deadlineAt, isAfter) {
    if (!deadlineAt) return '';
    return '<span class="deadline-chip' + (isAfter ? ' passed' : '') + '">' +
      '<span aria-hidden="true">' + (isAfter ? '🔒' : '⏰') + '</span>' +
      (isAfter ? '締め後 ' : '締め ') + esc(fmtDateTime(deadlineAt)) + '</span>';
  }

  /* ---------------- トースト ---------------- */
  function toast(message, kind) {
    const area = document.getElementById('toast-area');
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    const icon = kind === 'ok' ? '✔' : kind === 'err' ? '⚠' : kind === 'warn' ? '⚠' : 'ℹ';
    el.innerHTML = '<span aria-hidden="true">' + icon + '</span><span>' + esc(message) + '</span>';
    area.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .3s';
      el.style.opacity = '0';
      setTimeout(function () { el.remove(); }, 320);
    }, kind === 'err' ? 5200 : 3000);
  }

  /* ---------------- モーダル ---------------- */
  let modalResolve = null;

  function closeModal(result) {
    const root = document.getElementById('modal-root');
    root.innerHTML = '';
    if (modalResolve) { const r = modalResolve; modalResolve = null; r(result); }
  }

  /**
   * 確認ダイアログ。確定・削除の前に必ず挟む。
   * opts: {title, desc, rows:[{k,v}], okLabel, cancelLabel, danger}
   */
  function confirmDialog(opts) {
    return new Promise(function (resolve) {
      modalResolve = resolve;
      const rows = (opts.rows || []).map(function (r) {
        return '<div class="row"><span class="k">' + esc(r.k) + '</span><span class="v">' + esc(r.v) + '</span></div>';
      }).join('');
      const root = document.getElementById('modal-root');
      root.innerHTML =
        '<div class="modal-backdrop" data-close="1">' +
          '<div class="modal" role="dialog" aria-modal="true">' +
            '<h3>' + esc(opts.title) + '</h3>' +
            (opts.desc ? '<div class="modal-desc">' + esc(opts.desc) + '</div>' : '') +
            (rows ? '<div class="confirm-list">' + rows + '</div>' : '') +
            '<div class="modal-actions">' +
              '<button class="btn" data-act="cancel">' + esc(opts.cancelLabel || 'キャンセル') + '</button>' +
              '<button class="btn ' + (opts.danger ? 'btn-danger' : 'btn-primary') + '" data-act="ok">' +
                esc(opts.okLabel || 'OK') + '</button>' +
            '</div>' +
          '</div>' +
        '</div>';
      root.querySelector('[data-act="ok"]').onclick = function () { closeModal(true); };
      root.querySelector('[data-act="cancel"]').onclick = function () { closeModal(false); };
      root.querySelector('.modal-backdrop').onclick = function (e) {
        if (e.target.dataset.close) closeModal(false);
      };
    });
  }

  /**
   * 入力フォームつきモーダル。
   * fields: [{name, label, type, required, options, value, placeholder, min, help}]
   * 戻り値: 値オブジェクト（キャンセル時は null）
   */
  function formDialog(opts) {
    return new Promise(function (resolve) {
      modalResolve = resolve;
      const fields = opts.fields || [];
      const body = fields.map(function (f) {
        const req = f.required ? '<span class="req" aria-hidden="true">*</span>' : '';
        let input;
        if (f.type === 'select') {
          const options = (f.options || []).map(function (o) {
            return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(f.value) ? ' selected' : '') + '>' +
              esc(o.label) + '</option>';
          }).join('');
          input = '<select class="input" name="' + esc(f.name) + '">' + options + '</select>';
        } else if (f.type === 'textarea') {
          input = '<textarea class="input" name="' + esc(f.name) + '" placeholder="' + esc(f.placeholder || '') + '">' +
            esc(f.value || '') + '</textarea>';
        } else if (f.type === 'number') {
          // スマホで数字キーボードを出す
          input = '<input class="input" name="' + esc(f.name) + '" type="number" inputmode="numeric" pattern="[0-9]*"' +
            ' value="' + esc(f.value === undefined ? '' : f.value) + '" min="' + (f.min === undefined ? 0 : f.min) + '">';
        } else {
          input = '<input class="input" name="' + esc(f.name) + '" type="' + esc(f.type || 'text') + '"' +
            ' value="' + esc(f.value || '') + '" placeholder="' + esc(f.placeholder || '') + '">';
        }
        return '<div class="field"><label>' + esc(f.label) + req + '</label>' + input +
          (f.help ? '<div class="card-sub">' + esc(f.help) + '</div>' : '') + '</div>';
      }).join('');

      const root = document.getElementById('modal-root');
      root.innerHTML =
        '<div class="modal-backdrop" data-close="1">' +
          '<div class="modal" role="dialog" aria-modal="true">' +
            '<h3>' + esc(opts.title) + '</h3>' +
            (opts.desc ? '<div class="modal-desc">' + esc(opts.desc) + '</div>' : '') +
            '<div class="dlg-error"></div>' +
            '<form data-form>' + body + '</form>' +
            '<div class="modal-actions">' +
              '<button class="btn" data-act="cancel">キャンセル</button>' +
              '<button class="btn btn-primary" data-act="ok">' + esc(opts.okLabel || '保存') + '</button>' +
            '</div>' +
          '</div>' +
        '</div>';

      const form = root.querySelector('[data-form]');
      root.querySelector('[data-act="ok"]').onclick = function () {
        const values = {};
        let missing = null;
        fields.forEach(function (f) {
          const el = form.querySelector('[name="' + f.name + '"]');
          let v = el ? el.value : '';
          if (f.type === 'number') v = v === '' ? null : Number(v);
          if (f.required && (v === '' || v === null)) missing = missing || f.label;
          values[f.name] = v;
        });
        if (missing) {
          root.querySelector('.dlg-error').innerHTML =
            '<div class="alert-box err">' + esc(missing) + ' は必須です。入力してください。</div>';
          return;
        }
        closeModal(values);
      };
      root.querySelector('[data-act="cancel"]').onclick = function () { closeModal(null); };
      root.querySelector('.modal-backdrop').onclick = function (e) {
        if (e.target.dataset.close) closeModal(null);
      };
    });
  }

  /* ---------------- 数量ステッパー ---------------- */
  /** 数値入力欄（スマホで数字キーボード + ± ボタン）。 */
  function stepperHtml(name, label, value, opts) {
    opts = opts || {};
    return '<div class="qty-row">' +
      '<span class="qty-label">' + esc(label) + '</span>' +
      '<div class="stepper">' +
        '<button type="button" data-step="-1" data-target="' + esc(name) + '" aria-label="' + esc(label) + 'を1減らす">−</button>' +
        '<input type="number" inputmode="numeric" pattern="[0-9]*" min="0" ' +
          'name="' + esc(name) + '" value="' + esc(value === undefined || value === null ? 0 : value) + '"' +
          (opts.disabled ? ' disabled' : '') + ' aria-label="' + esc(label) + '">' +
        '<button type="button" data-step="1" data-target="' + esc(name) + '" aria-label="' + esc(label) + 'を1増やす">＋</button>' +
      '</div>' +
      (opts.suffix ? '<span class="qty-total">' + esc(opts.suffix) + '</span>' : '') +
    '</div>';
  }

  /** ± ボタンを配線する。root 配下の [data-step] を対象にする。 */
  function bindSteppers(root, onChange) {
    root.querySelectorAll('[data-step]').forEach(function (btn) {
      btn.onclick = function () {
        const input = root.querySelector('input[name="' + btn.dataset.target + '"]');
        if (!input || input.disabled) return;
        const next = Math.max(0, (parseInt(input.value, 10) || 0) + parseInt(btn.dataset.step, 10));
        input.value = next;
        if (onChange) onChange(btn.dataset.target, next);
      };
    });
    root.querySelectorAll('input[type="number"]').forEach(function (input) {
      input.oninput = function () {
        if (input.value !== '' && parseInt(input.value, 10) < 0) input.value = 0;
        if (onChange) onChange(input.name, parseInt(input.value, 10) || 0);
      };
    });
  }

  /* ---------------- 二重送信防止 ---------------- */
  /**
   * ボタンを押している間は無効化し、処理完了まで再送信させない。
   * 通信失敗時もボタンは必ず戻す。
   */
  function guard(button, fn) {
    if (!button) return fn();
    if (button.dataset.busy === '1') return Promise.resolve();
    button.dataset.busy = '1';
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<span aria-hidden="true">⏳</span>処理中...';
    return Promise.resolve()
      .then(fn)
      .finally(function () {
        button.dataset.busy = '0';
        button.disabled = false;
        button.innerHTML = original;
      });
  }

  /* ---------------- 未保存警告 ---------------- */
  let dirty = false;
  function setDirty(v) {
    dirty = !!v;
  }
  function isDirty() { return dirty; }
  window.addEventListener('beforeunload', function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  global.UI = {
    esc: esc,
    badge: badge,
    fmtDate: fmtDate,
    fmtDateTime: fmtDateTime,
    todayStr: todayStr,
    deadlineChip: deadlineChip,
    toast: toast,
    confirmDialog: confirmDialog,
    formDialog: formDialog,
    closeModal: closeModal,
    stepperHtml: stepperHtml,
    bindSteppers: bindSteppers,
    guard: guard,
    setDirty: setDirty,
    isDirty: isDirty,
    STATUS_STYLE: STATUS_STYLE,
  };
})(window);
