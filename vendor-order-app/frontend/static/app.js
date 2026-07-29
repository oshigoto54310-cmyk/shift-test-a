/* ベンダー別・発注管理Webアプリ フロントエンド本体。

   画面構成は権限で切り替える:
   - 管理者 / 本部 : ダッシュボード・発注・履歴・出力・マスタ（管理者のみ）
   - 店舗担当者    : 発注入力・自店舗発注・履歴・通知
   - ベンダー担当者: 受注一覧・集計・回答・回答履歴・通知（ベンダー切替UIは出さない）
*/
(function () {
  'use strict';

  const E = UI.esc;

  const state = {
    me: null,
    meta: null,
    stores: [],
    vendors: [],
    view: 'dashboard',
    filterVendorId: '',
    filterStoreId: '',
    filterDate: '',
    cart: [],            // 発注入力中の明細
    unread: 0,
    pollTimer: null,
  };

  const root = document.getElementById('app');

  /* ==================================================================
     起動
     ================================================================== */
  async function boot() {
    try {
      const [me, meta] = await Promise.all([Api.me(), Api.get('/api/meta')]);
      state.me = me;
      state.meta = meta;
      await loadScopeMasters();
      state.view = defaultView();
      render();
      startPolling();
    } catch (err) {
      renderLogin();
    }
  }

  function defaultView() {
    if (isVendor()) return 'vendor-orders';
    if (isStore()) return 'order-entry';
    return 'dashboard';
  }

  function isAdmin() { return state.me && state.me.role_code === 'ADMIN'; }
  function isHQ() { return state.me && (state.me.role_code === 'HQ' || state.me.role_code === 'ADMIN'); }
  function isStore() { return state.me && state.me.role_code === 'STORE'; }
  function isVendor() { return state.me && state.me.role_code === 'VENDOR'; }

  async function loadScopeMasters() {
    // ベンダーユーザーには自社しか返らない（サーバー側で絞り込み済み）
    const [stores, vendors] = await Promise.all([
      Api.get('/api/stores').catch(function () { return []; }),
      Api.get('/api/vendors').catch(function () { return []; }),
    ]);
    state.stores = stores || [];
    state.vendors = vendors || [];
  }

  /* ==================================================================
     ログイン画面
     ================================================================== */
  function renderLogin() {
    stopPolling();
    document.body.style.paddingBottom = '0';
    root.innerHTML =
      '<div class="login-wrap"><div class="login-card">' +
        '<h1>発注管理システム</h1>' +
        '<div class="sub">本部・店舗・ベンダー共通のログイン画面です</div>' +
        '<div id="login-error"></div>' +
        '<div class="field"><label for="login-email">メールアドレス<span class="req">*</span></label>' +
          '<input class="input" id="login-email" type="email" inputmode="email" autocomplete="username" placeholder="you@example.com"></div>' +
        '<div class="field"><label for="login-password">パスワード<span class="req">*</span></label>' +
          '<input class="input" id="login-password" type="password" autocomplete="current-password"></div>' +
        '<button class="btn btn-primary btn-block" id="login-btn">ログイン</button>' +
        '<button class="btn btn-ghost btn-block" id="reset-btn" style="margin-top:8px">パスワード再設定</button>' +
        '<div class="login-hint"><strong>動作確認用アカウント（架空データ）</strong><br>' +
          '管理者 <code>admin@example.invalid</code><br>' +
          '本部 <code>hq1@example.invalid</code><br>' +
          '店舗 <code>store1a@example.invalid</code><br>' +
          'ベンダー <code>vendor1a@example.invalid</code><br>' +
          'パスワード <code>Password123!</code></div>' +
      '</div></div>';

    const emailEl = document.getElementById('login-email');
    const pwEl = document.getElementById('login-password');
    const btn = document.getElementById('login-btn');

    async function doLogin() {
      const box = document.getElementById('login-error');
      box.innerHTML = '';
      if (!emailEl.value || !pwEl.value) {
        box.innerHTML = '<div class="alert-box err">メールアドレスとパスワードを入力してください。</div>';
        return;
      }
      await UI.guard(btn, async function () {
        try {
          state.me = await Api.login(emailEl.value, pwEl.value);
          state.meta = await Api.get('/api/meta');
          await loadScopeMasters();
          document.body.style.paddingBottom = '';
          state.view = defaultView();
          UI.toast('ログインしました', 'ok');
          render();
          startPolling();
        } catch (err) {
          box.innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>';
        }
      });
    }

    btn.onclick = doLogin;
    pwEl.onkeydown = function (e) { if (e.key === 'Enter') doLogin(); };
    document.getElementById('reset-btn').onclick = async function () {
      const v = await UI.formDialog({
        title: 'パスワード再設定',
        desc: '登録済みのメールアドレスあてに再設定用トークンを送信します。',
        fields: [{ name: 'email', label: 'メールアドレス', type: 'email', required: true }],
        okLabel: '送信',
      });
      if (!v) return;
      try {
        const r = await Api.requestPasswordReset(v.email);
        UI.toast(r.message, 'ok');
      } catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  /* ==================================================================
     共通レイアウト
     ================================================================== */
  function navItems() {
    if (isVendor()) {
      return [
        { key: 'vendor-orders', label: '受注一覧' },
        { key: 'vendor-summary', label: '集計' },
        { key: 'vendor-history', label: '回答履歴' },
        { key: 'notifications', label: '通知' },
      ];
    }
    if (isStore()) {
      return [
        { key: 'order-entry', label: '発注入力' },
        { key: 'orders', label: '発注一覧' },
        { key: 'change-requests', label: '変更申請' },
        { key: 'history', label: '履歴' },
        { key: 'notifications', label: '通知' },
      ];
    }
    const items = [
      { key: 'dashboard', label: 'ダッシュボード' },
      { key: 'orders', label: '発注一覧' },
      { key: 'order-entry', label: '発注登録' },
      { key: 'change-requests', label: '変更申請' },
      { key: 'vendor-summary', label: '集計' },
      { key: 'history', label: '履歴' },
      { key: 'exports', label: '出力' },
      { key: 'notifications', label: '通知' },
    ];
    if (isAdmin()) items.push({ key: 'masters', label: 'マスタ管理' });
    return items;
  }

  function headerHtml() {
    const canSwitch = state.me.can_switch_vendor;
    let switcher = '';
    if (canSwitch) {
      // ベンダー切替・店舗切替は管理者と本部のみ表示する
      const vOptions = ['<option value="">全ベンダー</option>'].concat(
        state.vendors.map(function (v) {
          return '<option value="' + v.id + '"' + (String(v.id) === String(state.filterVendorId) ? ' selected' : '') +
            '>' + E(v.name) + '</option>';
        })
      ).join('');
      const sOptions = ['<option value="">全店舗</option>'].concat(
        state.stores.map(function (s) {
          return '<option value="' + s.id + '"' + (String(s.id) === String(state.filterStoreId) ? ' selected' : '') +
            '>' + E(s.name) + '</option>';
        })
      ).join('');
      switcher =
        '<div class="switcher-row">' +
          '<div class="switcher"><label for="sw-vendor">ベンダー</label><select id="sw-vendor">' + vOptions + '</select></div>' +
          '<div class="switcher"><label for="sw-store">店舗</label><select id="sw-store">' + sOptions + '</select></div>' +
          '<div class="switcher"><label for="sw-date">納品日</label>' +
            '<select id="sw-date">' + dateOptions() + '</select></div>' +
        '</div>';
    }

    const scopeLine = isVendor() ? E(state.me.vendor_name || '')
      : isStore() ? E(state.me.store_name || '') : '全店舗・全ベンダー';

    return '<header class="app-header">' +
      '<div class="app-header-row">' +
        '<div class="app-title">発注管理</div>' +
        '<div class="app-user"><strong>' + E(state.me.name) + '</strong>' +
          E(state.me.role_label) + ' / ' + scopeLine +
          ' <button class="btn btn-sm btn-ghost" id="logout-btn" style="color:#fff;border-color:rgba(255,255,255,.5);margin-left:6px">ログアウト</button>' +
        '</div>' +
      '</div>' + switcher +
    '</header>';
  }

  function dateOptions() {
    const opts = ['<option value="">すべての納品日</option>'];
    for (let i = -7; i <= 14; i++) {
      const v = UI.todayStr(i);
      const label = UI.fmtDate(v) + (i === 0 ? '（本日）' : i === 1 ? '（明日）' : '');
      opts.push('<option value="' + v + '"' + (v === state.filterDate ? ' selected' : '') + '>' + E(label) + '</option>');
    }
    return opts.join('');
  }

  function navHtml() {
    return '<nav class="nav">' + navItems().map(function (n) {
      const badgeHtml = (n.key === 'notifications' && state.unread)
        ? ' <span class="badge-count">' + state.unread + '</span>' : '';
      return '<button data-view="' + n.key + '"' + (state.view === n.key ? ' aria-current="page"' : '') + '>' +
        E(n.label) + badgeHtml + '</button>';
    }).join('') + '</nav>';
  }

  function render() {
    root.innerHTML = headerHtml() + navHtml() + '<div class="container" id="view"><div class="loading">読み込み中...</div></div>';

    document.getElementById('logout-btn').onclick = async function () {
      const ok = await UI.confirmDialog({ title: 'ログアウトしますか？', okLabel: 'ログアウト' });
      if (!ok) return;
      try { await Api.logout(); } catch (e) { /* セッション切れでも画面は戻す */ }
      state.me = null;
      renderLogin();
    };

    root.querySelectorAll('.nav button').forEach(function (b) {
      b.onclick = function () {
        if (UI.isDirty()) {
          UI.confirmDialog({
            title: '保存されていない入力があります',
            desc: 'このまま移動すると入力内容は破棄されます。',
            okLabel: '破棄して移動', danger: true,
          }).then(function (ok) {
            if (!ok) return;
            UI.setDirty(false);
            state.view = b.dataset.view;
            render();
          });
          return;
        }
        state.view = b.dataset.view;
        render();
      };
    });

    const vSel = document.getElementById('sw-vendor');
    if (vSel) vSel.onchange = function () { state.filterVendorId = vSel.value; render(); };
    const sSel = document.getElementById('sw-store');
    if (sSel) sSel.onchange = function () { state.filterStoreId = sSel.value; render(); };
    const dSel = document.getElementById('sw-date');
    if (dSel) dSel.onchange = function () { state.filterDate = dSel.value; render(); };

    renderView();
    refreshUnread();
  }

  function view() { return document.getElementById('view'); }

  function scopeParams(extra) {
    const p = Object.assign({}, extra || {});
    // ベンダー／店舗ユーザーは送っても無視される（サーバー側で強制）。
    // 管理者・本部の切替のみ意味を持つ。
    if (state.me.can_switch_vendor && state.filterVendorId) p.vendor_id = state.filterVendorId;
    if (state.me.can_switch_store && state.filterStoreId) p.store_id = state.filterStoreId;
    return p;
  }

  async function renderView() {
    const v = view();
    try {
      switch (state.view) {
        case 'dashboard': return await viewDashboard(v);
        case 'orders': return await viewOrders(v);
        case 'order-entry': return await viewOrderEntry(v);
        case 'change-requests': return await viewChangeRequests(v);
        case 'vendor-orders': return await viewVendorOrders(v);
        case 'vendor-summary': return await viewVendorSummary(v);
        case 'vendor-history': return await viewVendorHistory(v);
        case 'history': return await viewHistory(v);
        case 'exports': return viewExports(v);
        case 'notifications': return await viewNotifications(v);
        case 'masters': return await viewMasters(v);
        default: v.innerHTML = '<div class="empty">画面が見つかりません</div>';
      }
    } catch (err) {
      if (err.isUnauthorized) { renderLogin(); return; }
      v.innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>';
    }
  }

  /* ==================================================================
     ダッシュボード（本部・管理者）
     ================================================================== */
  async function viewDashboard(v) {
    const d = await Api.get('/api/dashboard', scopeParams(state.filterDate ? { delivery_date: state.filterDate } : {}));
    const tiles = [
      { k: 'today_deadline_count', label: '本日締め', icon: '⏰', cls: 'warn', to: 'orders' },
      { k: 'unconfirmed_count', label: '未確定', icon: '✎', cls: '', to: 'orders' },
      { k: 'vendor_pending_count', label: 'ベンダー未確認', icon: '⏳', cls: 'warn', to: 'orders' },
      { k: 'reply_overdue_count', label: '回答期限超過', icon: '⚠', cls: 'alert', to: 'orders' },
      { k: 'shortage_count', label: '欠品', icon: '✖', cls: 'alert', to: 'orders' },
      { k: 'partial_count', label: '一部納品', icon: '◐', cls: 'warn', to: 'orders' },
      { k: 'substitute_count', label: '代替提案', icon: '⇄', cls: '', to: 'orders' },
      { k: 'change_request_count', label: '変更申請', icon: '📝', cls: 'warn', to: 'change-requests' },
    ];
    v.innerHTML =
      '<div class="page-title">本部ダッシュボード</div>' +
      '<div class="page-desc">' +
        (state.filterVendorId ? 'ベンダー絞り込み中' : '全ベンダー') + ' / ' +
        (state.filterStoreId ? '店舗絞り込み中' : '全店舗') + ' / ' +
        (state.filterDate ? '納品日 ' + E(UI.fmtDate(state.filterDate)) : 'すべての納品日') +
      '</div>' +
      '<div class="stats">' + tiles.map(function (t) {
        return '<button class="stat ' + t.cls + '" data-to="' + t.to + '">' +
          '<div class="label"><span aria-hidden="true">' + t.icon + '</span>' + E(t.label) + '</div>' +
          '<div class="num">' + (d[t.k] || 0) + '</div></button>';
      }).join('') + '</div>' +
      '<div class="section" style="margin-top:22px"><div class="section-title">直近の発注</div><div id="recent"></div></div>';

    v.querySelectorAll('.stat').forEach(function (b) {
      b.onclick = function () { state.view = b.dataset.to; render(); };
    });

    const orders = await Api.get('/api/orders', scopeParams({ limit: 8 }));
    document.getElementById('recent').innerHTML = orders.length
      ? orders.map(orderCardHtml).join('')
      : '<div class="empty">該当する発注はありません</div>';
    bindOrderCards(document.getElementById('recent'));
  }

  /* ==================================================================
     発注一覧
     ================================================================== */
  function orderCardHtml(o) {
    return '<div class="card" data-order="' + o.id + '">' +
      '<div class="card-head">' +
        '<div><div class="card-title">' + E(o.order_no) + '</div>' +
        '<div class="card-sub">' + E(o.store_name || '') + ' → ' + E(o.vendor_name || '') + '</div></div>' +
        UI.badge(o.status, o.status_label) +
      '</div>' +
      '<div class="card-grid">' +
        '<div><div class="k">納品日</div><div class="v">' + E(UI.fmtDate(o.delivery_date)) + '</div></div>' +
        '<div><div class="k">明細数</div><div class="v">' + o.item_count + '</div></div>' +
        '<div><div class="k">合計数量</div><div class="v">' + o.total_quantity + '</div></div>' +
        '<div><div class="k">締め</div><div class="v">' + UI.deadlineChip(o.deadline_at, o.is_after_deadline) + '</div></div>' +
      '</div>' +
      '<div class="card-actions"><button class="btn btn-sm" data-detail="' + o.id + '">明細を見る</button></div>' +
    '</div>';
  }

  function bindOrderCards(container) {
    container.querySelectorAll('[data-detail]').forEach(function (b) {
      b.onclick = function () { openOrderDetail(parseInt(b.dataset.detail, 10)); };
    });
  }

  async function viewOrders(v) {
    v.innerHTML =
      '<div class="page-title">発注一覧</div>' +
      '<div class="page-desc">' + (isStore() ? '自店舗の発注のみ表示されます' : '切替中の範囲の発注を表示します') + '</div>' +
      '<div class="chip-row" id="status-chips">' +
        ['', 'DRAFT', 'CONFIRMED', 'VENDOR_PENDING', 'SHORTAGE', 'PARTIAL', 'CHANGE_REQUESTED'].map(function (s) {
          const label = s === '' ? 'すべて' : (state.meta.order_statuses[s] || s);
          return '<button class="chip" data-status="' + s + '" aria-pressed="' + (s === '' ? 'true' : 'false') + '">' + E(label) + '</button>';
        }).join('') +
      '</div>' +
      '<div id="order-list"><div class="loading">読み込み中...</div></div>';

    let statusFilter = '';
    async function load() {
      const params = scopeParams({ limit: 100 });
      if (state.filterDate) params.delivery_date = state.filterDate;
      if (statusFilter) params.status = statusFilter;
      const orders = await Api.get('/api/orders', params);
      const list = document.getElementById('order-list');
      list.innerHTML = orders.length ? orders.map(orderCardHtml).join('')
        : '<div class="empty">該当する発注はありません</div>';
      bindOrderCards(list);
    }

    v.querySelectorAll('#status-chips .chip').forEach(function (c) {
      c.onclick = function () {
        v.querySelectorAll('#status-chips .chip').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
        c.setAttribute('aria-pressed', 'true');
        statusFilter = c.dataset.status;
        load();
      };
    });
    await load();
  }

  /* ==================================================================
     発注明細
     ================================================================== */
  async function openOrderDetail(orderId) {
    const v = view();
    v.innerHTML = '<div class="loading">読み込み中...</div>';
    let order, editable;
    try {
      order = await Api.get('/api/orders/' + orderId);
      editable = await Api.get('/api/orders/' + orderId + '/editable');
    } catch (err) {
      v.innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>' +
        '<button class="btn" id="back">戻る</button>';
      document.getElementById('back').onclick = function () { render(); };
      return;
    }

    const afterDeadline = editable.is_after_deadline;
    const canEdit = editable.can_edit_directly;

    const itemsHtml = order.items.map(function (it) {
      const r = it.latest_response;
      return '<div class="card">' +
        '<div class="card-head">' +
          '<div><div class="card-title">' + E(it.product_name) + '</div>' +
            '<div class="card-sub">' + E(it.spec || '') + ' / JAN ' + E(it.jan_code) + '</div></div>' +
          UI.badge(it.status, it.status_label) +
        '</div>' +
        '<div class="card-grid">' +
          '<div><div class="k">ケース</div><div class="v">' + it.qty_case + '</div></div>' +
          '<div><div class="k">バラ</div><div class="v">' + it.qty_loose + '</div></div>' +
          '<div><div class="k">発注数量</div><div class="v">' + it.quantity + '</div></div>' +
          '<div><div class="k">確定数量</div><div class="v">' +
            (it.confirmed_quantity === null || it.confirmed_quantity === undefined ? '—' : it.confirmed_quantity) + '</div></div>' +
        '</div>' +
        (r ? '<div class="alert-box ' + (r.response_type === 'SHORTAGE' ? 'err' : r.response_type === 'PARTIAL' ? 'warn' : 'info') + '" style="margin-top:10px">' +
              '<strong>ベンダー回答: ' + E(r.response_label) + '</strong><br>' +
              (r.deliverable_qty !== null && r.deliverable_qty !== undefined ? '納品可能 ' + r.deliverable_qty + ' / ' : '') +
              (r.shortage_qty ? '不足 ' + r.shortage_qty + '<br>' : '<br>') +
              E(r.reason || r.shortage_reason || '') +
              (r.next_available_date ? '<br>次回納品可能日: ' + E(UI.fmtDate(r.next_available_date)) : '') +
              (r.sub_product_name ? '<br>代替提案: ' + E(r.sub_product_name) +
                 ' ' + (r.sub_deliverable_qty || 0) + '個' +
                 (r.sub_approved_at ? '（承認済み）' : r.sub_rejected_at ? '（却下）' : '（本部承認待ち）') : '') +
            '</div>' : '') +
        (afterDeadline && !isVendor() && it.status !== 'CANCELLED'
          ? '<div class="card-actions"><button class="btn btn-sm" data-cr="' + it.id + '" data-name="' + E(it.product_name) +
            '" data-case="' + it.qty_case + '" data-loose="' + it.qty_loose + '">締め後の変更申請</button></div>'
          : '') +
      '</div>';
    }).join('');

    v.innerHTML =
      '<button class="btn btn-sm btn-ghost" id="back" style="margin-bottom:10px">← 一覧へ戻る</button>' +
      '<div class="page-title">' + E(order.order_no) + '</div>' +
      '<div class="page-desc">' + E(order.store_name) + ' → ' + E(order.vendor_name) +
        ' / 納品日 ' + E(UI.fmtDate(order.delivery_date)) + '</div>' +
      '<div class="card">' +
        '<div class="card-head"><div class="card-title">発注ステータス</div>' + UI.badge(order.status, order.status_label) + '</div>' +
        '<div class="card-grid">' +
          '<div><div class="k">最終締め</div><div class="v">' + UI.deadlineChip(order.deadline_at, afterDeadline) + '</div></div>' +
          '<div><div class="k">回答期限</div><div class="v">' + E(UI.fmtDateTime(order.reply_deadline_at)) + '</div></div>' +
          '<div><div class="k">合計数量</div><div class="v">' + order.total_quantity + '</div></div>' +
          '<div><div class="k">確定日時</div><div class="v">' + (order.confirmed_at ? E(UI.fmtDateTime(order.confirmed_at)) : '—') + '</div></div>' +
        '</div>' +
      '</div>' +
      (afterDeadline
        ? '<div class="alert-box warn"><span aria-hidden="true">🔒</span> <strong>締め時間を過ぎています。</strong>数量は直接変更できません。変更申請を行い、本部の承認を受けてください。</div>'
        : '') +
      '<div class="section-title">発注明細（' + order.items.length + '件）</div>' +
      itemsHtml +
      '<div class="section" style="margin-top:18px"><div class="section-title">この発注の変更履歴</div><div id="order-hist"><div class="loading">読み込み中...</div></div></div>' +
      '<div class="bottom-bar">' +
        '<button class="btn back" id="back2">戻る</button>' +
        (canEdit ? '<button class="btn" id="edit-btn">数量を修正</button>' : '') +
        (canEdit && (order.status === 'DRAFT' || order.status === 'PLANNED')
          ? '<button class="btn btn-primary" id="confirm-btn">発注確定</button>' : '') +
        (isVendor() && ['CONFIRMED', 'VENDOR_PENDING'].indexOf(order.status) >= 0
          ? '<button class="btn btn-primary" id="ack-btn">受注確認</button>' : '') +
      '</div>';

    document.getElementById('back').onclick = function () { render(); };
    document.getElementById('back2').onclick = function () { render(); };

    const editBtn = document.getElementById('edit-btn');
    if (editBtn) editBtn.onclick = function () { openOrderEdit(order); };

    const confirmBtn = document.getElementById('confirm-btn');
    if (confirmBtn) confirmBtn.onclick = function () { doConfirmOrder(order, confirmBtn); };

    const ackBtn = document.getElementById('ack-btn');
    if (ackBtn) ackBtn.onclick = function () {
      UI.guard(ackBtn, async function () {
        const ok = await UI.confirmDialog({
          title: '受注確認を送信しますか？',
          desc: 'この発注を受け付けたことが店舗・本部に通知されます。',
          rows: [{ k: '発注番号', v: order.order_no }, { k: '納品日', v: UI.fmtDate(order.delivery_date) }],
          okLabel: '受注確認',
        });
        if (!ok) return;
        try {
          await Api.post('/api/vendor/ack', { order_id: order.id });
          UI.toast('受注確認を送信しました', 'ok');
          openOrderDetail(order.id);
        } catch (err) { UI.toast(err.message, 'err'); }
      });
    };

    v.querySelectorAll('[data-cr]').forEach(function (b) {
      b.onclick = function () { openChangeRequestDialog(b, order.id); };
    });

    Api.get('/api/histories/quantity', { order_id: order.id, limit: 50 }).then(function (rows) {
      const box = document.getElementById('order-hist');
      if (!box) return;
      box.innerHTML = rows.length ? '<div class="timeline">' + rows.map(function (h) {
        return '<div class="timeline-item' + (h.is_after_deadline ? ' after-deadline' : '') + '">' +
          '<div class="timeline-time">' + E(UI.fmtDateTime(h.changed_at)) + ' / ' + E(h.changed_by_name || '—') +
            ' / ' + (h.is_after_deadline ? '締め後' : '締め前') + '</div>' +
          '<div class="timeline-body"><strong>' + E(h.product_name || '') + '</strong> ' +
            (h.qty_before || 0) + ' → ' + (h.qty_after || 0) +
            (h.reason ? '（' + E(h.reason) + '）' : '') +
            (h.reject_reason ? ' <span class="badge alert">却下: ' + E(h.reject_reason) + '</span>' : '') +
          '</div></div>';
      }).join('') + '</div>' : '<div class="empty">履歴はありません</div>';
    }).catch(function () { });
  }

  async function doConfirmOrder(order, btn) {
    await UI.guard(btn, async function () {
      const ok = await UI.confirmDialog({
        title: 'この内容で発注を確定しますか？',
        desc: '確定後はベンダーへ通知されます。締め時間を過ぎると直接修正できなくなります。',
        rows: [
          { k: '発注番号', v: order.order_no },
          { k: '納品先', v: order.store_name },
          { k: 'ベンダー', v: order.vendor_name },
          { k: '納品日', v: UI.fmtDate(order.delivery_date) },
          { k: '明細数', v: order.item_count + ' 件' },
          { k: '合計数量', v: order.total_quantity },
        ],
        okLabel: '発注確定',
      });
      if (!ok) return;
      try {
        await Api.post('/api/orders/' + order.id + '/confirm', { client_token: Api.newToken() });
        UI.toast('発注を確定しました', 'ok');
        openOrderDetail(order.id);
      } catch (err) { UI.toast(err.message, 'err'); }
    });
  }

  /* 締め前の数量修正 */
  function openOrderEdit(order) {
    const v = view();
    const rows = order.items.map(function (it) {
      return '<div class="card" data-item="' + it.id + '" data-product="' + it.product_id + '">' +
        '<div class="card-title">' + E(it.product_name) + '</div>' +
        '<div class="card-sub">' + E(it.spec || '') + ' / ケース入数 ' + it.case_qty + '</div>' +
        UI.stepperHtml('case-' + it.id, 'ケース', it.qty_case) +
        UI.stepperHtml('loose-' + it.id, 'バラ', it.qty_loose) +
      '</div>';
    }).join('');

    v.innerHTML =
      '<button class="btn btn-sm btn-ghost" id="back" style="margin-bottom:10px">← 戻る</button>' +
      '<div class="page-title">数量の修正</div>' +
      '<div class="page-desc">' + E(order.order_no) + ' / 締め ' + E(UI.fmtDateTime(order.deadline_at)) +
        '（締め前のため直接修正できます。修正内容は履歴に残ります）</div>' +
      '<div class="field"><label>変更理由（任意）</label>' +
        '<input class="input" id="edit-reason" placeholder="例）売上予測の変更"></div>' +
      rows +
      '<div class="bottom-bar">' +
        '<button class="btn back" id="cancel-edit">戻る</button>' +
        '<button class="btn btn-primary" id="save-edit">保存</button>' +
      '</div>';

    UI.bindSteppers(v, function () { UI.setDirty(true); });
    UI.setDirty(false);

    function leave(fn) {
      if (!UI.isDirty()) return fn();
      UI.confirmDialog({
        title: '保存されていない変更があります', desc: '破棄して戻りますか？',
        okLabel: '破棄して戻る', danger: true,
      }).then(function (ok) { if (ok) { UI.setDirty(false); fn(); } });
    }
    document.getElementById('back').onclick = function () { leave(function () { openOrderDetail(order.id); }); };
    document.getElementById('cancel-edit').onclick = function () { leave(function () { openOrderDetail(order.id); }); };

    const saveBtn = document.getElementById('save-edit');
    saveBtn.onclick = function () {
      UI.guard(saveBtn, async function () {
        const reason = document.getElementById('edit-reason').value;
        const items = [];
        const changes = [];
        v.querySelectorAll('[data-item]').forEach(function (card) {
          const id = parseInt(card.dataset.item, 10);
          const qtyCase = parseInt(card.querySelector('input[name="case-' + id + '"]').value, 10) || 0;
          const qtyLoose = parseInt(card.querySelector('input[name="loose-' + id + '"]').value, 10) || 0;
          items.push({ id: id, product_id: parseInt(card.dataset.product, 10), qty_case: qtyCase, qty_loose: qtyLoose, reason: reason });
          const before = order.items.find(function (x) { return x.id === id; });
          if (before && (before.qty_case !== qtyCase || before.qty_loose !== qtyLoose)) {
            changes.push({ k: before.product_name, v: before.qty_case + 'C/' + before.qty_loose + '本 → ' + qtyCase + 'C/' + qtyLoose + '本' });
          }
        });
        if (!changes.length) { UI.toast('変更はありません', 'warn'); return; }

        const ok = await UI.confirmDialog({
          title: 'この内容で保存しますか？', desc: '変更内容は履歴に記録されます。',
          rows: changes, okLabel: '保存',
        });
        if (!ok) return;
        try {
          await Api.put('/api/orders/' + order.id, { items: items, client_token: Api.newToken() });
          UI.setDirty(false);
          UI.toast('保存しました', 'ok');
          openOrderDetail(order.id);
        } catch (err) { UI.toast(err.message, 'err'); }
      });
    };
  }

  /* ==================================================================
     発注入力
     ================================================================== */
  async function viewOrderEntry(v) {
    if (isVendor()) { v.innerHTML = '<div class="empty">ベンダー担当者は発注登録できません</div>'; return; }

    const needStore = !isStore();
    v.innerHTML =
      '<div class="page-title">発注入力</div>' +
      '<div class="page-desc">商品を検索してカゴに入れ、数量を入力してください。</div>' +
      (needStore
        ? '<div class="field"><label>発注する店舗<span class="req">*</span></label><select class="input" id="entry-store">' +
          state.stores.map(function (s) {
            return '<option value="' + s.id + '"' + (String(s.id) === String(state.filterStoreId) ? ' selected' : '') + '>' + E(s.name) + '</option>';
          }).join('') + '</select></div>'
        : '') +
      '<div class="field"><label>納品日<span class="req">*</span></label>' +
        '<input class="input" id="entry-date" type="date" value="' + E(state.filterDate || UI.todayStr(2)) + '" min="' + UI.todayStr(0) + '"></div>' +
      '<div class="chip-row">' +
        '<button class="chip" id="tab-search" aria-pressed="true">商品検索</button>' +
        '<button class="chip" id="tab-fav">お気に入り</button>' +
        '<button class="chip" id="tab-recent">前回発注商品</button>' +
        '<button class="chip" id="tab-copy">前回発注をコピー</button>' +
      '</div>' +
      '<div class="filters">' +
        '<div class="field"><label>商品名 / JAN / 自社コード</label>' +
          '<input class="input" id="q" placeholder="例）牛乳 または 02000..." inputmode="search"></div>' +
        '<div class="field"><label>分類</label><select class="input" id="cat"><option value="">すべて</option></select></div>' +
        '<div class="field"><label>ベンダー</label><select class="input" id="vend"><option value="">すべて</option>' +
          state.vendors.map(function (x) { return '<option value="' + x.id + '">' + E(x.name) + '</option>'; }).join('') +
        '</select></div>' +
      '</div>' +
      '<div id="product-list"><div class="loading">読み込み中...</div></div>' +
      '<div class="section" style="margin-top:20px"><div class="section-title">発注カゴ（<span id="cart-count">0</span>件）</div>' +
        '<div id="cart-area"><div class="empty">商品を追加してください</div></div></div>' +
      '<div class="bottom-bar">' +
        '<button class="btn" id="save-draft">一時保存</button>' +
        '<button class="btn btn-primary" id="submit-order">発注確定</button>' +
      '</div>';

    Api.get('/api/products/categories').then(function (cats) {
      const sel = document.getElementById('cat');
      if (!sel) return;
      cats.forEach(function (c) {
        const o = document.createElement('option');
        o.value = c; o.textContent = c;
        sel.appendChild(o);
      });
    }).catch(function () { });

    let mode = 'search';
    const qEl = document.getElementById('q');
    const catEl = document.getElementById('cat');
    const vendEl = document.getElementById('vend');

    async function loadProducts() {
      const list = document.getElementById('product-list');
      list.innerHTML = '<div class="loading">読み込み中...</div>';
      let items = [];
      try {
        if (mode === 'fav') {
          items = await Api.get('/api/favorites', isStore() ? {} : { store_id: currentStoreId() });
        } else if (mode === 'recent') {
          const rows = await Api.get('/api/orders/helpers/recent-products', isStore() ? {} : { store_id: currentStoreId() });
          items = rows.map(function (r) {
            return { id: r.product_id, jan_code: r.jan_code, name: r.name, spec: r.spec, case_qty: r.case_qty,
                     order_unit: r.order_unit, allow_loose: r.allow_loose, vendor_name: r.vendor_name };
          });
        } else {
          items = await Api.get('/api/products', {
            q: qEl.value, category: catEl.value, vendor_id: vendEl.value, limit: 60,
          });
        }
      } catch (err) {
        list.innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>';
        return;
      }
      list.innerHTML = items.length ? items.map(function (p) {
        return '<div class="card">' +
          '<div class="card-head"><div>' +
            '<div class="card-title">' + E(p.name) + '</div>' +
            '<div class="card-sub">' + E(p.spec || '') + ' / ' + E(p.vendor_name || '') +
              ' / ケース入数 ' + (p.case_qty || 1) + ' / JAN ' + E(p.jan_code) + '</div>' +
          '</div></div>' +
          '<div class="card-actions">' +
            '<button class="btn btn-sm btn-primary" data-add="' + p.id + '">カゴに追加</button>' +
            (mode !== 'fav' ? '<button class="btn btn-sm" data-fav="' + p.id + '">★ お気に入り</button>' : '') +
          '</div></div>';
      }).join('') : '<div class="empty">該当する商品がありません</div>';

      list.querySelectorAll('[data-add]').forEach(function (b) {
        b.onclick = function () {
          const p = items.find(function (x) { return String(x.id) === b.dataset.add; });
          addToCart(p);
        };
      });
      list.querySelectorAll('[data-fav]').forEach(function (b) {
        b.onclick = async function () {
          try {
            await Api.post('/api/favorites/' + b.dataset.fav + (isStore() ? '' : '?store_id=' + currentStoreId()));
            UI.toast('お気に入りに登録しました', 'ok');
          } catch (err) { UI.toast(err.message, 'err'); }
        };
      });
    }

    function currentStoreId() {
      const el = document.getElementById('entry-store');
      return el ? parseInt(el.value, 10) : state.me.store_id;
    }

    function setTab(key) {
      mode = key;
      ['search', 'fav', 'recent'].forEach(function (k) {
        const el = document.getElementById('tab-' + k);
        if (el) el.setAttribute('aria-pressed', String(k === key));
      });
      loadProducts();
    }
    document.getElementById('tab-search').onclick = function () { setTab('search'); };
    document.getElementById('tab-fav').onclick = function () { setTab('fav'); };
    document.getElementById('tab-recent').onclick = function () { setTab('recent'); };
    document.getElementById('tab-copy').onclick = async function () {
      try {
        const r = await Api.get('/api/orders/helpers/last-order', isStore() ? {} : { store_id: currentStoreId() });
        if (!r.order) { UI.toast('前回の発注が見つかりません', 'warn'); return; }
        state.cart = r.items.map(function (i) {
          return { product_id: i.product_id, name: i.product_name, spec: i.spec, case_qty: i.case_qty,
                   order_unit: i.order_unit, allow_loose: true, qty_case: i.qty_case, qty_loose: i.qty_loose };
        });
        renderCart();
        UI.toast('前回発注（' + r.order.order_no + '）をコピーしました', 'ok');
      } catch (err) { UI.toast(err.message, 'err'); }
    };

    let searchTimer = null;
    [qEl, catEl, vendEl].forEach(function (el) {
      el.oninput = el.onchange = function () {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(function () { if (mode === 'search') loadProducts(); }, 280);
      };
    });

    function addToCart(p) {
      if (!p) return;
      if (state.cart.some(function (c) { return c.product_id === p.id; })) {
        UI.toast('すでにカゴに入っています', 'warn');
        return;
      }
      state.cart.push({
        product_id: p.id, name: p.name, spec: p.spec, case_qty: p.case_qty || 1,
        order_unit: p.order_unit, allow_loose: p.allow_loose !== false, qty_case: 1, qty_loose: 0,
      });
      renderCart();
      UI.toast(p.name + ' を追加しました', 'ok');
    }

    function renderCart() {
      const area = document.getElementById('cart-area');
      document.getElementById('cart-count').textContent = state.cart.length;
      UI.setDirty(state.cart.length > 0);
      if (!state.cart.length) { area.innerHTML = '<div class="empty">商品を追加してください</div>'; return; }
      area.innerHTML = state.cart.map(function (c, idx) {
        const total = c.case_qty * c.qty_case + c.qty_loose;
        return '<div class="card" data-cart="' + idx + '">' +
          '<div class="card-head"><div>' +
            '<div class="card-title">' + E(c.name) + '</div>' +
            '<div class="card-sub">' + E(c.spec || '') + ' / ケース入数 ' + c.case_qty +
              ' / 発注単位 ' + E(state.meta.order_units[c.order_unit] || c.order_unit) + '</div>' +
          '</div><button class="btn btn-sm" data-remove="' + idx + '" aria-label="削除">✕</button></div>' +
          UI.stepperHtml('cart-case-' + idx, 'ケース', c.qty_case, { disabled: c.order_unit === 'PIECE' }) +
          UI.stepperHtml('cart-loose-' + idx, 'バラ', c.qty_loose, { disabled: !c.allow_loose || c.order_unit === 'CASE' }) +
          '<div class="qty-row"><span class="qty-label">合計</span>' +
            '<span class="qty-total"><strong id="cart-total-' + idx + '">' + total + '</strong> 個（バラ換算）</span></div>' +
        '</div>';
      }).join('');

      UI.bindSteppers(area, function (name) {
        const m = name.match(/^cart-(case|loose)-(\d+)$/);
        if (!m) return;
        const idx = parseInt(m[2], 10);
        const el = area.querySelector('input[name="' + name + '"]');
        const val = parseInt(el.value, 10) || 0;
        if (m[1] === 'case') state.cart[idx].qty_case = val; else state.cart[idx].qty_loose = val;
        const c = state.cart[idx];
        const t = document.getElementById('cart-total-' + idx);
        if (t) t.textContent = c.case_qty * c.qty_case + c.qty_loose;
        UI.setDirty(true);
      });

      area.querySelectorAll('[data-remove]').forEach(function (b) {
        b.onclick = async function () {
          const idx = parseInt(b.dataset.remove, 10);
          const ok = await UI.confirmDialog({
            title: 'この商品をカゴから削除しますか？',
            rows: [{ k: '商品名', v: state.cart[idx].name }], okLabel: '削除', danger: true,
          });
          if (!ok) return;
          state.cart.splice(idx, 1);
          renderCart();
        };
      });
    }

    async function submit(confirmFlag, btn) {
      await UI.guard(btn, async function () {
        if (!state.cart.length) { UI.toast('商品がカゴに入っていません', 'warn'); return; }
        const deliveryDate = document.getElementById('entry-date').value;
        if (!deliveryDate) { UI.toast('納品日を選択してください', 'err'); return; }

        const payload = {
          delivery_date: deliveryDate,
          items: state.cart.map(function (c) {
            return { product_id: c.product_id, qty_case: c.qty_case, qty_loose: c.qty_loose };
          }),
          confirm: confirmFlag,
          client_token: Api.newToken(),
        };
        if (!isStore()) payload.store_id = currentStoreId();

        // 事前チェック（重複・異常数量・締め超過など）
        let warnings = [];
        try {
          const check = await Api.post('/api/orders/validate', {
            store_id: payload.store_id, delivery_date: deliveryDate, items: payload.items,
          });
          warnings = check.warnings || [];
          if (check.blocking) {
            await UI.confirmDialog({
              title: '登録できません',
              desc: warnings.filter(function (w) { return w.level === 'ERROR'; }).map(function (w) { return w.message; }).join('\n'),
              okLabel: '閉じる', cancelLabel: '閉じる',
            });
            return;
          }
        } catch (err) { UI.toast(err.message, 'err'); return; }

        const rows = [
          { k: '納品日', v: UI.fmtDate(deliveryDate) },
          { k: '明細数', v: state.cart.length + ' 件' },
          { k: '合計数量', v: state.cart.reduce(function (a, c) { return a + c.case_qty * c.qty_case + c.qty_loose; }, 0) },
        ];
        warnings.forEach(function (w) { rows.push({ k: '⚠ 確認', v: w.message }); });

        const ok = await UI.confirmDialog({
          title: confirmFlag ? 'この内容で発注を確定しますか？' : 'この内容で一時保存しますか？',
          desc: confirmFlag
            ? '確定後はベンダーへ通知されます。締め時間を過ぎると直接修正できなくなります。'
            : '一時保存した発注は、あとから修正して確定できます。',
          rows: rows,
          okLabel: confirmFlag ? '発注確定' : '一時保存',
        });
        if (!ok) return;

        try {
          const created = await Api.post('/api/orders', payload);
          state.cart = [];
          UI.setDirty(false);
          UI.toast(
            (confirmFlag ? '発注を確定しました' : '一時保存しました') +
            '（' + created.map(function (o) { return o.order_no; }).join(', ') + '）', 'ok');
          state.view = 'orders';
          render();
        } catch (err) { UI.toast(err.message, 'err'); }
      });
    }

    const draftBtn = document.getElementById('save-draft');
    const submitBtn = document.getElementById('submit-order');
    draftBtn.onclick = function () { submit(false, draftBtn); };
    submitBtn.onclick = function () { submit(true, submitBtn); };

    renderCart();
    await loadProducts();
  }

  /* ==================================================================
     変更申請
     ================================================================== */
  async function openChangeRequestDialog(btn, orderId) {
    const values = await UI.formDialog({
      title: '締め後の変更申請',
      desc: btn.dataset.name + ' の数量変更を申請します。本部の承認後に反映されます。',
      fields: [
        { name: 'case', label: '変更後ケース数', type: 'number', value: btn.dataset.case, required: true, min: 0 },
        { name: 'loose', label: '変更後バラ数', type: 'number', value: btn.dataset.loose, required: true, min: 0 },
        { name: 'reason', label: '変更理由', type: 'textarea', required: true, placeholder: '例）天候不良により需要が減少したため' },
      ],
      okLabel: '申請する',
    });
    if (!values) return;
    try {
      await Api.post('/api/change-requests', {
        order_item_id: parseInt(btn.dataset.cr, 10),
        requested_case: values.case, requested_loose: values.loose,
        reason: values.reason, client_token: Api.newToken(),
      });
      UI.toast('変更申請を送信しました', 'ok');
      openOrderDetail(orderId);
    } catch (err) { UI.toast(err.message, 'err'); }
  }

  async function viewChangeRequests(v) {
    v.innerHTML = '<div class="page-title">変更申請</div>' +
      '<div class="page-desc">' + (isHQ() ? '申請の承認・却下を行います。' : '自分の申請の状況を確認できます。') + '</div>' +
      '<div id="cr-list"><div class="loading">読み込み中...</div></div>';

    const rows = await Api.get('/api/change-requests', scopeParams({ limit: 100 }));
    const list = document.getElementById('cr-list');
    list.innerHTML = rows.length ? rows.map(function (cr) {
      return '<div class="card">' +
        '<div class="card-head"><div>' +
          '<div class="card-title">' + E(cr.product_name || '') + '</div>' +
          '<div class="card-sub">' + E(cr.order_no || '') + ' / ' + E(cr.store_name || '') + ' → ' + E(cr.vendor_name || '') +
            ' / 納品日 ' + E(UI.fmtDate(cr.delivery_date)) + '</div>' +
        '</div>' + UI.badge(cr.status, cr.status_label) + '</div>' +
        '<div class="card-grid">' +
          '<div><div class="k">変更前</div><div class="v">' + cr.before_quantity + '</div></div>' +
          '<div><div class="k">変更後（申請）</div><div class="v">' + cr.requested_quantity + '</div></div>' +
          '<div><div class="k">申請者</div><div class="v">' + E(cr.requester_name || '') + '</div></div>' +
          '<div><div class="k">申請日時</div><div class="v">' + E(UI.fmtDateTime(cr.requested_at)) + '</div></div>' +
        '</div>' +
        '<div class="alert-box info" style="margin-top:10px"><strong>変更理由:</strong> ' + E(cr.reason) + '</div>' +
        (cr.reject_reason ? '<div class="alert-box err"><strong>却下理由:</strong> ' + E(cr.reject_reason) + '</div>' : '') +
        (cr.vendor_confirmed_at ? '<div class="alert-box info">ベンダー確認済み ' + E(UI.fmtDateTime(cr.vendor_confirmed_at)) + '</div>' : '') +
        (isHQ() && cr.status === 'PENDING'
          ? '<div class="card-actions">' +
              '<button class="btn btn-sm btn-ok" data-approve="' + cr.id + '">承認</button>' +
              '<button class="btn btn-sm btn-danger" data-reject="' + cr.id + '">却下</button></div>'
          : '') +
        (isVendor() && cr.status === 'APPROVED' && !cr.vendor_confirmed_at
          ? '<div class="card-actions"><button class="btn btn-sm btn-primary" data-vconfirm="' + cr.id + '">変更内容を確認</button></div>'
          : '') +
      '</div>';
    }).join('') : '<div class="empty">変更申請はありません</div>';

    list.querySelectorAll('[data-approve]').forEach(function (b) {
      b.onclick = function () {
        UI.guard(b, async function () {
          const ok = await UI.confirmDialog({
            title: 'この変更申請を承認しますか？',
            desc: '承認すると発注数量が更新され、変更履歴に記録されます。', okLabel: '承認する',
          });
          if (!ok) return;
          try {
            await Api.post('/api/change-requests/' + b.dataset.approve + '/decision', { approve: true });
            UI.toast('承認しました', 'ok');
            renderView();
          } catch (err) { UI.toast(err.message, 'err'); }
        });
      };
    });
    list.querySelectorAll('[data-reject]').forEach(function (b) {
      b.onclick = async function () {
        const values = await UI.formDialog({
          title: '変更申請を却下', desc: '却下理由は申請者に通知されます。',
          fields: [{ name: 'reason', label: '却下理由', type: 'textarea', required: true }],
          okLabel: '却下する',
        });
        if (!values) return;
        try {
          await Api.post('/api/change-requests/' + b.dataset.reject + '/decision',
            { approve: false, reject_reason: values.reason });
          UI.toast('却下しました', 'ok');
          renderView();
        } catch (err) { UI.toast(err.message, 'err'); }
      };
    });
    list.querySelectorAll('[data-vconfirm]').forEach(function (b) {
      b.onclick = function () {
        UI.guard(b, async function () {
          try {
            await Api.post('/api/change-requests/' + b.dataset.vconfirm + '/vendor-confirm');
            UI.toast('確認しました', 'ok');
            renderView();
          } catch (err) { UI.toast(err.message, 'err'); }
        });
      };
    });
  }

  /* ==================================================================
     ベンダー画面
     ================================================================== */
  async function viewVendorOrders(v) {
    v.innerHTML =
      '<div class="page-title">受注一覧</div>' +
      '<div class="page-desc">自社あての発注のみ表示されます。商品ごとに回答してください。</div>' +
      '<div class="filters">' +
        '<div class="field"><label>納品日</label><input class="input" type="date" id="vd-date" value="' + E(state.filterDate) + '"></div>' +
      '</div>' +
      '<div id="vlist"><div class="loading">読み込み中...</div></div>';

    document.getElementById('vd-date').onchange = function (e) {
      state.filterDate = e.target.value; load();
    };

    async function load() {
      const params = { include_items: true, limit: 60 };
      if (state.filterDate) params.delivery_date = state.filterDate;
      const orders = await Api.get('/api/orders', params);
      const list = document.getElementById('vlist');
      if (!orders.length) { list.innerHTML = '<div class="empty">該当する受注はありません</div>'; return; }

      list.innerHTML = orders.map(function (o) {
        const items = (o.items || []).map(function (it) {
          const r = it.latest_response;
          return '<div class="card" style="margin:8px 0 0;background:var(--surface-2)">' +
            '<div class="card-head"><div>' +
              '<div class="card-title">' + E(it.product_name) + '</div>' +
              '<div class="card-sub">' + E(it.spec || '') + ' / JAN ' + E(it.jan_code) + '</div>' +
            '</div>' + UI.badge(it.status, it.status_label) + '</div>' +
            '<div class="card-grid">' +
              '<div><div class="k">店舗</div><div class="v">' + E(o.store_name) + '</div></div>' +
              '<div><div class="k">発注数量</div><div class="v">' + it.quantity + '</div></div>' +
              '<div><div class="k">ケース/バラ</div><div class="v">' + it.qty_case + ' / ' + it.qty_loose + '</div></div>' +
              '<div><div class="k">確定数量</div><div class="v">' +
                (it.confirmed_quantity === null || it.confirmed_quantity === undefined ? '—' : it.confirmed_quantity) + '</div></div>' +
            '</div>' +
            (r ? '<div class="card-sub" style="margin-top:6px">前回回答: ' + E(r.response_label) + ' / ' + E(UI.fmtDateTime(r.responded_at)) + '</div>' : '') +
            '<div class="card-actions">' +
              '<button class="btn btn-sm btn-ok" data-full="' + it.id + '" data-qty="' + it.quantity + '" data-name="' + E(it.product_name) + '">全数納品</button>' +
              '<button class="btn btn-sm" data-partial="' + it.id + '" data-qty="' + it.quantity + '" data-name="' + E(it.product_name) + '">一部納品</button>' +
              '<button class="btn btn-sm btn-danger" data-short="' + it.id + '" data-name="' + E(it.product_name) + '">欠品</button>' +
              '<button class="btn btn-sm" data-sub="' + it.id + '" data-qty="' + it.quantity + '" data-name="' + E(it.product_name) + '">代替提案</button>' +
            '</div></div>';
        }).join('');

        return '<div class="card">' +
          '<div class="card-head"><div>' +
            '<div class="card-title">' + E(o.order_no) + '</div>' +
            '<div class="card-sub">' + E(o.store_name) + ' / 納品日 ' + E(UI.fmtDate(o.delivery_date)) + '</div>' +
          '</div>' + UI.badge(o.status, o.status_label) + '</div>' +
          '<div class="card-sub" style="margin-top:6px">' + UI.deadlineChip(o.reply_deadline_at, false).replace('締め', '回答期限') + '</div>' +
          (['CONFIRMED', 'VENDOR_PENDING'].indexOf(o.status) >= 0
            ? '<div class="card-actions"><button class="btn btn-sm btn-primary" data-ack="' + o.id + '">受注確認</button></div>' : '') +
          items + '</div>';
      }).join('');

      bindVendorActions(list, load);
    }
    await load();
  }

  function bindVendorActions(list, reload) {
    list.querySelectorAll('[data-ack]').forEach(function (b) {
      b.onclick = function () {
        UI.guard(b, async function () {
          const ok = await UI.confirmDialog({ title: '受注確認を送信しますか？', okLabel: '受注確認' });
          if (!ok) return;
          try {
            await Api.post('/api/vendor/ack', { order_id: parseInt(b.dataset.ack, 10) });
            UI.toast('受注確認しました', 'ok'); reload();
          } catch (err) { UI.toast(err.message, 'err'); }
        });
      };
    });

    list.querySelectorAll('[data-full]').forEach(function (b) {
      b.onclick = function () {
        UI.guard(b, async function () {
          const ok = await UI.confirmDialog({
            title: '全数納品で回答しますか？',
            rows: [{ k: '商品', v: b.dataset.name }, { k: '納品数量', v: b.dataset.qty }],
            okLabel: '全数納品で回答',
          });
          if (!ok) return;
          await sendResponse({ order_item_id: parseInt(b.dataset.full, 10), response_type: 'FULL' }, reload);
        });
      };
    });

    list.querySelectorAll('[data-partial]').forEach(function (b) {
      b.onclick = async function () {
        const values = await UI.formDialog({
          title: '一部納品の回答',
          desc: b.dataset.name + '（発注数量 ' + b.dataset.qty + '）',
          fields: [
            { name: 'qty', label: '納品可能数量', type: 'number', required: true, min: 1,
              help: '発注数量より少ない数を入力してください' },
            { name: 'reason', label: '理由', type: 'textarea', required: true, placeholder: '例）生産遅延のため' },
          ],
          okLabel: '回答する',
        });
        if (!values) return;
        await sendResponse({
          order_item_id: parseInt(b.dataset.partial, 10), response_type: 'PARTIAL',
          deliverable_qty: values.qty, reason: values.reason,
        }, reload);
      };
    });

    list.querySelectorAll('[data-short]').forEach(function (b) {
      b.onclick = async function () {
        const values = await UI.formDialog({
          title: '欠品の回答', desc: b.dataset.name,
          fields: [
            { name: 'reason', label: '欠品理由', type: 'textarea', required: true },
            { name: 'next', label: '次回納品可能日', type: 'date' },
          ],
          okLabel: '欠品として回答',
        });
        if (!values) return;
        await sendResponse({
          order_item_id: parseInt(b.dataset.short, 10), response_type: 'SHORTAGE',
          shortage_reason: values.reason, next_available_date: values.next || null,
        }, reload);
      };
    });

    list.querySelectorAll('[data-sub]').forEach(function (b) {
      b.onclick = async function () {
        const values = await UI.formDialog({
          title: '代替商品の提案', desc: b.dataset.name + ' の代わりに納品できる商品を提案します（本部承認後に確定）。',
          fields: [
            { name: 'name', label: '代替商品名', type: 'text', required: true },
            { name: 'jan', label: 'JANコード', type: 'text' },
            { name: 'spec', label: '規格', type: 'text' },
            { name: 'cost', label: '原価', type: 'number', min: 0 },
            { name: 'qty', label: '納品可能数量', type: 'number', required: true, min: 1 },
            { name: 'date', label: '納品可能日', type: 'date' },
            { name: 'comment', label: 'コメント', type: 'textarea' },
          ],
          okLabel: '提案する',
        });
        if (!values) return;
        await sendResponse({
          order_item_id: parseInt(b.dataset.sub, 10), response_type: 'SUBSTITUTE',
          sub_product_name: values.name, sub_jan_code: values.jan, sub_spec: values.spec,
          sub_cost: values.cost, sub_deliverable_qty: values.qty,
          sub_delivery_date: values.date || null, sub_comment: values.comment,
          deliverable_qty: 0,
        }, reload);
      };
    });
  }

  async function sendResponse(payload, reload) {
    try {
      payload.client_token = Api.newToken();
      await Api.post('/api/vendor/responses', payload);
      UI.toast('回答を送信しました', 'ok');
      reload();
    } catch (err) { UI.toast(err.message, 'err'); }
  }

  async function viewVendorSummary(v) {
    v.innerHTML =
      '<div class="page-title">集計</div>' +
      '<div class="page-desc">' + (isVendor() ? '自社分の集計のみ表示されます。' : '切替中の範囲で集計します。') + '</div>' +
      '<div class="chip-row">' +
        '<button class="chip" id="sum-product" aria-pressed="true">商品別合計</button>' +
        '<button class="chip" id="sum-date">納品日別</button>' +
        '<button class="chip" id="sum-store">店舗別</button>' +
      '</div>' +
      '<div id="sum-body"><div class="loading">読み込み中...</div></div>';

    async function showProduct() {
      const params = scopeParams(state.filterDate ? { delivery_date: state.filterDate } : {});
      const rows = await Api.get('/api/vendor/summary/by-product', params);
      document.getElementById('sum-body').innerHTML = rows.length ? rows.map(function (r) {
        return '<div class="card">' +
          '<div class="card-title">' + E(r.product_name) + '</div>' +
          '<div class="card-sub">' + E(r.spec || '') + ' / JAN ' + E(r.jan_code) + ' / ケース入数 ' + r.case_qty + '</div>' +
          '<div class="card-grid">' +
            '<div><div class="k">合計数量</div><div class="v">' + r.total_quantity + '</div></div>' +
            '<div><div class="k">合計ケース</div><div class="v">' + r.total_case + '</div></div>' +
            '<div><div class="k">合計バラ</div><div class="v">' + r.total_loose + '</div></div>' +
            '<div><div class="k">発注店舗数</div><div class="v">' + r.store_breakdown.length + '</div></div>' +
          '</div>' +
          '<div class="card-sub" style="margin-top:8px"><strong>店舗別内訳</strong></div>' +
          r.store_breakdown.map(function (s) {
            return '<div class="confirm-list" style="margin:6px 0 0"><div class="row">' +
              '<span class="k">' + E(s.store_name) + '</span>' +
              '<span class="v">' + s.quantity + '（' + s.qty_case + 'C / ' + s.qty_loose + '本）</span></div></div>';
          }).join('') +
        '</div>';
      }).join('') : '<div class="empty">データがありません</div>';
    }

    async function showDate() {
      const rows = await Api.get('/api/vendor/summary/by-delivery-date', scopeParams());
      document.getElementById('sum-body').innerHTML = rows.length
        ? '<div class="table-wrap"><table><thead><tr><th>納品日</th><th class="num">発注件数</th>' +
          '<th class="num">明細数</th><th class="num">合計数量</th><th class="num">未回答</th>' +
          '<th class="num">欠品</th><th class="num">一部納品</th></tr></thead><tbody>' +
          rows.map(function (r) {
            return '<tr><td>' + E(UI.fmtDate(r.delivery_date)) + '</td><td class="num">' + r.order_count +
              '</td><td class="num">' + r.item_count + '</td><td class="num">' + r.total_quantity +
              '</td><td class="num">' + r.pending_count + '</td><td class="num">' + r.shortage_count +
              '</td><td class="num">' + r.partial_count + '</td></tr>';
          }).join('') + '</tbody></table></div>'
        : '<div class="empty">データがありません</div>';
    }

    async function showStore() {
      const params = scopeParams(state.filterDate ? { delivery_date: state.filterDate } : {});
      const rows = await Api.get('/api/vendor/summary/by-store', params);
      document.getElementById('sum-body').innerHTML = rows.length ? rows.map(function (r) {
        return '<div class="card"><div class="card-head">' +
          '<div class="card-title">' + E(r.store_name) + '</div>' +
          '<span class="badge primary">' + r.total_quantity + ' 個</span></div>' +
          '<div class="card-sub">発注件数 ' + r.order_count + '</div></div>';
      }).join('') : '<div class="empty">データがありません</div>';
    }

    function setTab(id, fn) {
      ['sum-product', 'sum-date', 'sum-store'].forEach(function (k) {
        document.getElementById(k).setAttribute('aria-pressed', String(k === id));
      });
      document.getElementById('sum-body').innerHTML = '<div class="loading">読み込み中...</div>';
      fn().catch(function (err) {
        document.getElementById('sum-body').innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>';
      });
    }
    document.getElementById('sum-product').onclick = function () { setTab('sum-product', showProduct); };
    document.getElementById('sum-date').onclick = function () { setTab('sum-date', showDate); };
    document.getElementById('sum-store').onclick = function () { setTab('sum-store', showStore); };
    setTab('sum-product', showProduct);
  }

  async function viewVendorHistory(v) {
    v.innerHTML = '<div class="page-title">回答履歴</div>' +
      '<div class="page-desc">自社の回答履歴（訂正前の回答も残ります）</div>' +
      '<div id="vh"><div class="loading">読み込み中...</div></div>';
    const rows = await Api.get('/api/vendor/responses', scopeParams({ limit: 100 }));
    document.getElementById('vh').innerHTML = rows.length ? rows.map(function (r) {
      return '<div class="card">' +
        '<div class="card-head"><div class="card-title">' + E(r.response_label) + '</div>' +
          (r.is_latest ? '<span class="badge ok">最新</span>' : '<span class="badge neutral">訂正前</span>') + '</div>' +
        '<div class="card-grid">' +
          '<div><div class="k">発注数量</div><div class="v">' + (r.ordered_qty || 0) + '</div></div>' +
          '<div><div class="k">納品可能</div><div class="v">' + (r.deliverable_qty === null ? '—' : r.deliverable_qty) + '</div></div>' +
          '<div><div class="k">不足</div><div class="v">' + (r.shortage_qty === null ? '—' : r.shortage_qty) + '</div></div>' +
          '<div><div class="k">回答日時</div><div class="v">' + E(UI.fmtDateTime(r.responded_at)) + '</div></div>' +
        '</div>' +
        ((r.reason || r.shortage_reason) ? '<div class="card-sub" style="margin-top:8px">理由: ' + E(r.reason || r.shortage_reason) + '</div>' : '') +
        (r.sub_product_name ? '<div class="card-sub">代替: ' + E(r.sub_product_name) + '</div>' : '') +
      '</div>';
    }).join('') : '<div class="empty">回答履歴はありません</div>';
  }

  /* ==================================================================
     履歴
     ================================================================== */
  async function viewHistory(v) {
    const tabs = [
      { k: 'qty', label: '数量変更履歴' },
      { k: 'status', label: 'ステータス履歴' },
      { k: 'resp', label: 'ベンダー回答' },
    ];
    if (isHQ()) {
      tabs.push({ k: 'audit', label: '操作ログ' });
      tabs.push({ k: 'notif', label: '通知履歴' });
    }
    if (isAdmin()) tabs.push({ k: 'login', label: 'ログイン履歴' });

    v.innerHTML = '<div class="page-title">履歴</div>' +
      '<div class="page-desc">履歴は削除できません。すべての変更が記録されています。</div>' +
      '<div class="chip-row" id="h-tabs">' + tabs.map(function (t, i) {
        return '<button class="chip" data-h="' + t.k + '" aria-pressed="' + (i === 0 ? 'true' : 'false') + '">' + E(t.label) + '</button>';
      }).join('') + '</div><div id="h-body"><div class="loading">読み込み中...</div></div>';

    async function load(kind) {
      const body = document.getElementById('h-body');
      body.innerHTML = '<div class="loading">読み込み中...</div>';
      try {
        if (kind === 'qty') {
          const rows = await Api.get('/api/histories/quantity', scopeParams({ limit: 150 }));
          body.innerHTML = rows.length ? '<div class="timeline">' + rows.map(function (h) {
            return '<div class="timeline-item' + (h.is_after_deadline ? ' after-deadline' : '') + '">' +
              '<div class="timeline-time">' + E(UI.fmtDateTime(h.changed_at)) + ' / ' + E(h.changed_by_name || '—') +
                ' / <strong>' + (h.is_after_deadline ? '締め後' : '締め前') + '</strong></div>' +
              '<div class="timeline-body">' + E(h.order_no || '') + ' ' + E(h.product_name || '') + ' : ' +
                (h.qty_before || 0) + ' → ' + (h.qty_after || 0) +
                ' （ケース ' + (h.case_before || 0) + '→' + (h.case_after || 0) +
                ' / バラ ' + (h.loose_before || 0) + '→' + (h.loose_after || 0) + '）' +
                (h.reason ? '<br>理由: ' + E(h.reason) : '') +
                (h.reject_reason ? '<br>却下理由: ' + E(h.reject_reason) : '') +
                (h.vendor_confirmed_at ? '<br>ベンダー確認: ' + E(UI.fmtDateTime(h.vendor_confirmed_at)) : '') +
              '</div></div>';
          }).join('') + '</div>' : '<div class="empty">履歴はありません</div>';
        } else if (kind === 'status') {
          const rows = await Api.get('/api/histories/status', scopeParams({ limit: 150 }));
          body.innerHTML = rows.length ? '<div class="timeline">' + rows.map(function (h) {
            return '<div class="timeline-item">' +
              '<div class="timeline-time">' + E(UI.fmtDateTime(h.changed_at)) + ' / ' + E(h.changed_by_name || '—') + '</div>' +
              '<div class="timeline-body">' + E(h.order_no || '') + ' : ' +
                (h.status_before_label ? UI.badge(h.status_before, h.status_before_label) + ' → ' : '') +
                UI.badge(h.status_after, h.status_after_label) +
                (h.note ? ' <span class="card-sub">' + E(h.note) + '</span>' : '') +
              '</div></div>';
          }).join('') + '</div>' : '<div class="empty">履歴はありません</div>';
        } else if (kind === 'resp') {
          const rows = await Api.get('/api/vendor/responses', scopeParams({ limit: 150 }));
          body.innerHTML = rows.length ? '<div class="timeline">' + rows.map(function (r) {
            return '<div class="timeline-item">' +
              '<div class="timeline-time">' + E(UI.fmtDateTime(r.responded_at)) + ' / ' + E(r.responder_name || '—') + '</div>' +
              '<div class="timeline-body">' + UI.badge(r.response_type, r.response_label) +
                ' 発注 ' + (r.ordered_qty || 0) + ' → 納品可能 ' + (r.deliverable_qty === null ? '—' : r.deliverable_qty) +
                (r.reason || r.shortage_reason ? '<br>' + E(r.reason || r.shortage_reason) : '') +
              '</div></div>';
          }).join('') + '</div>' : '<div class="empty">回答履歴はありません</div>';
        } else if (kind === 'audit') {
          const rows = await Api.get('/api/histories/audit', { limit: 200 });
          body.innerHTML = rows.length ? '<div class="table-wrap"><table><thead><tr>' +
            '<th>日時</th><th>ユーザー</th><th>権限</th><th>操作</th><th>対象</th><th>詳細</th></tr></thead><tbody>' +
            rows.map(function (r) {
              return '<tr><td>' + E(UI.fmtDateTime(r.created_at)) + '</td><td>' + E(r.user_email || '') + '</td>' +
                '<td>' + E(r.role_code || '') + '</td><td>' + E(r.action_label || r.action) + '</td>' +
                '<td>' + E((r.target_type || '') + ' ' + (r.target_id || '')) + '</td>' +
                '<td>' + E((r.detail || '').slice(0, 120)) + '</td></tr>';
            }).join('') + '</tbody></table></div>' : '<div class="empty">ログはありません</div>';
        } else if (kind === 'notif') {
          const rows = await Api.get('/api/histories/notification-logs', { limit: 200 });
          body.innerHTML = rows.length ? '<div class="table-wrap"><table><thead><tr>' +
            '<th>送信日時</th><th>チャネル</th><th>宛先</th><th>種別</th><th>結果</th></tr></thead><tbody>' +
            rows.map(function (r) {
              return '<tr><td>' + E(UI.fmtDateTime(r.sent_at)) + '</td><td>' + E(r.channel) + '</td>' +
                '<td>' + E(r.to_address || '') + '</td><td>' + E(r.type) + '</td><td>' + E(r.status) + '</td></tr>';
            }).join('') + '</tbody></table></div>' : '<div class="empty">通知履歴はありません</div>';
        } else if (kind === 'login') {
          const rows = await Api.get('/api/histories/login', { limit: 200 });
          body.innerHTML = rows.length ? '<div class="table-wrap"><table><thead><tr>' +
            '<th>日時</th><th>メール</th><th>結果</th><th>理由</th><th>IP</th></tr></thead><tbody>' +
            rows.map(function (r) {
              return '<tr><td>' + E(UI.fmtDateTime(r.created_at)) + '</td><td>' + E(r.email) + '</td>' +
                '<td>' + (r.success ? '成功' : '失敗') + '</td><td>' + E(r.failure_reason || '') + '</td>' +
                '<td>' + E(r.ip_address || '') + '</td></tr>';
            }).join('') + '</tbody></table></div>' : '<div class="empty">ログイン履歴はありません</div>';
        }
      } catch (err) {
        body.innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>';
      }
    }

    v.querySelectorAll('#h-tabs .chip').forEach(function (c) {
      c.onclick = function () {
        v.querySelectorAll('#h-tabs .chip').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
        c.setAttribute('aria-pressed', 'true');
        load(c.dataset.h);
      };
    });
    load('qty');
  }

  /* ==================================================================
     出力
     ================================================================== */
  function viewExports(v) {
    const items = [
      { path: '/api/exports/orders', label: 'ベンダー別 発注一覧', params: { group_by: 'vendor' } },
      { path: '/api/exports/orders', label: '店舗別 発注一覧', params: { group_by: 'store' } },
      { path: '/api/exports/product-summary', label: '商品別 集約', params: {} },
      { path: '/api/exports/delivery-date-summary', label: '納品日別 集約', params: {} },
      { path: '/api/exports/shortages', label: '欠品一覧', params: {} },
      { path: '/api/exports/partials', label: '一部納品一覧', params: {} },
      { path: '/api/exports/unanswered', label: '未回答一覧', params: {} },
      { path: '/api/exports/change-requests', label: '変更申請一覧', params: {} },
      { path: '/api/exports/order-histories', label: '発注変更履歴', params: {} },
    ];
    if (isHQ()) items.push({ path: '/api/exports/audit-logs', label: '操作ログ', params: {} });

    v.innerHTML = '<div class="page-title">出力</div>' +
      '<div class="page-desc">出力できるのは、いま自分が閲覧できる範囲のデータだけです。</div>' +
      items.map(function (it, idx) {
        return '<div class="card"><div class="card-title">' + E(it.label) + '</div>' +
          '<div class="card-actions">' +
            '<button class="btn btn-sm btn-primary" data-dl="' + idx + '" data-fmt="xlsx">Excel</button>' +
            '<button class="btn btn-sm" data-dl="' + idx + '" data-fmt="csv">CSV</button>' +
            '<button class="btn btn-sm" data-dl="' + idx + '" data-fmt="pdf">印刷/PDF</button>' +
          '</div></div>';
      }).join('');

    v.querySelectorAll('[data-dl]').forEach(function (b) {
      b.onclick = function () {
        UI.guard(b, async function () {
          const it = items[parseInt(b.dataset.dl, 10)];
          const params = Object.assign({ fmt: b.dataset.fmt }, it.params, scopeParams());
          if (state.filterDate && it.path.indexOf('summary') < 0) params.delivery_date = state.filterDate;
          try {
            await Api.download(it.path, params);
            UI.toast('出力しました', 'ok');
          } catch (err) { UI.toast(err.message, 'err'); }
        });
      };
    });
  }

  /* ==================================================================
     通知
     ================================================================== */
  async function viewNotifications(v) {
    v.innerHTML = '<div class="page-title">通知</div>' +
      '<div class="card-actions" style="margin-bottom:10px"><button class="btn btn-sm" id="read-all">すべて既読にする</button></div>' +
      '<div id="notif"><div class="loading">読み込み中...</div></div>';

    document.getElementById('read-all').onclick = async function () {
      try { await Api.post('/api/notifications/read-all'); renderView(); refreshUnread(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };

    const rows = await Api.get('/api/notifications', { limit: 100 });
    document.getElementById('notif').innerHTML = rows.length ? rows.map(function (n) {
      return '<div class="card" style="' + (n.is_read ? 'opacity:.65' : '') + '">' +
        '<div class="card-head"><div>' +
          '<div class="card-title">' + E(n.title) + '</div>' +
          '<div class="card-sub">' + E(UI.fmtDateTime(n.created_at)) + ' / ' + E(n.type_label || n.type) + '</div>' +
        '</div>' + (n.is_read ? '<span class="badge neutral">既読</span>' : '<span class="badge alert">未読</span>') + '</div>' +
        (n.body ? '<div class="card-sub" style="margin-top:8px">' + E(n.body) + '</div>' : '') +
        (n.order_id ? '<div class="card-actions"><button class="btn btn-sm" data-open="' + n.order_id + '">発注を開く</button></div>' : '') +
      '</div>';
    }).join('') : '<div class="empty">通知はありません</div>';

    v.querySelectorAll('[data-open]').forEach(function (b) {
      b.onclick = function () { openOrderDetail(parseInt(b.dataset.open, 10)); };
    });
  }

  async function refreshUnread() {
    try {
      const r = await Api.get('/api/notifications/unread-count');
      state.unread = r.unread || 0;
      const btn = document.querySelector('.nav button[data-view="notifications"]');
      if (btn) {
        const label = navItems().find(function (n) { return n.key === 'notifications'; });
        btn.innerHTML = E(label.label) + (state.unread ? ' <span class="badge-count">' + state.unread + '</span>' : '');
      }
    } catch (e) { /* 未ログイン時は無視 */ }
  }

  /* ==================================================================
     マスタ管理（管理者）
     ================================================================== */
  async function viewMasters(v) {
    v.innerHTML = '<div class="page-title">マスタ管理</div>' +
      '<div class="chip-row" id="m-tabs">' +
        ['stores:店舗', 'vendors:ベンダー', 'products:商品', 'users:ユーザー', 'deadlines:締め時間', 'reasons:理由'].map(function (s, i) {
          const p = s.split(':');
          return '<button class="chip" data-m="' + p[0] + '" aria-pressed="' + (i === 0 ? 'true' : 'false') + '">' + E(p[1]) + '</button>';
        }).join('') +
      '</div><div id="m-body"><div class="loading">読み込み中...</div></div>';

    async function load(kind) {
      const body = document.getElementById('m-body');
      body.innerHTML = '<div class="loading">読み込み中...</div>';
      try {
        if (kind === 'stores') await renderStores(body);
        else if (kind === 'vendors') await renderVendors(body);
        else if (kind === 'products') await renderProducts(body);
        else if (kind === 'users') await renderUsers(body);
        else if (kind === 'deadlines') await renderDeadlines(body);
        else if (kind === 'reasons') await renderReasons(body);
      } catch (err) {
        body.innerHTML = '<div class="alert-box err">' + E(err.message) + '</div>';
      }
    }

    v.querySelectorAll('#m-tabs .chip').forEach(function (c) {
      c.onclick = function () {
        v.querySelectorAll('#m-tabs .chip').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
        c.setAttribute('aria-pressed', 'true');
        load(c.dataset.m);
      };
    });
    load('stores');
  }

  async function renderStores(body) {
    const rows = await Api.get('/api/stores', { include_inactive: true });
    body.innerHTML = '<button class="btn btn-primary btn-sm" id="add" style="margin-bottom:10px">＋ 店舗を追加</button>' +
      rows.map(function (s) {
        return '<div class="card"><div class="card-head"><div>' +
          '<div class="card-title">' + E(s.name) + '</div><div class="card-sub">' + E(s.code) + ' / ' + E(s.address || '') + '</div>' +
          '</div>' + (s.is_active ? '<span class="badge ok">有効</span>' : '<span class="badge neutral">無効</span>') + '</div></div>';
      }).join('');
    document.getElementById('add').onclick = async function () {
      const val = await UI.formDialog({
        title: '店舗を追加',
        fields: [
          { name: 'code', label: '店舗コード', required: true },
          { name: 'name', label: '店舗名', required: true },
          { name: 'address', label: '住所' },
          { name: 'phone', label: '電話番号' },
        ],
      });
      if (!val) return;
      try { await Api.post('/api/stores', val); UI.toast('登録しました', 'ok'); await loadScopeMasters(); renderView(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  async function renderVendors(body) {
    const rows = await Api.get('/api/vendors', { include_inactive: true });
    body.innerHTML = '<button class="btn btn-primary btn-sm" id="add" style="margin-bottom:10px">＋ ベンダーを追加</button>' +
      rows.map(function (s) {
        return '<div class="card"><div class="card-head"><div>' +
          '<div class="card-title">' + E(s.name) + '</div>' +
          '<div class="card-sub">' + E(s.code) + ' / ' + E(s.contact_name || '') + ' / ' + E(s.email || '') + '</div>' +
          '</div>' + (s.is_active ? '<span class="badge ok">有効</span>' : '<span class="badge neutral">無効</span>') + '</div></div>';
      }).join('');
    document.getElementById('add').onclick = async function () {
      const val = await UI.formDialog({
        title: 'ベンダーを追加',
        fields: [
          { name: 'code', label: 'ベンダーコード', required: true },
          { name: 'name', label: 'ベンダー名', required: true },
          { name: 'contact_name', label: '担当者名' },
          { name: 'email', label: 'メールアドレス', type: 'email' },
          { name: 'phone', label: '電話番号' },
        ],
      });
      if (!val) return;
      try { await Api.post('/api/vendors', val); UI.toast('登録しました', 'ok'); await loadScopeMasters(); renderView(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  async function renderProducts(body) {
    const rows = await Api.get('/api/products', { include_inactive: true, limit: 300 });
    body.innerHTML = '<button class="btn btn-primary btn-sm" id="add" style="margin-bottom:10px">＋ 商品を追加</button>' +
      '<div class="table-wrap"><table><thead><tr><th>自社コード</th><th>JAN</th><th>商品名</th><th>分類</th>' +
      '<th class="num">ケース入数</th><th>単位</th><th class="num">原価</th><th>ベンダー</th><th>状態</th></tr></thead><tbody>' +
      rows.map(function (p) {
        return '<tr><td>' + E(p.own_code) + '</td><td>' + E(p.jan_code) + '</td><td>' + E(p.name) + '</td>' +
          '<td>' + E(p.category || '') + '</td><td class="num">' + p.case_qty + '</td><td>' + E(p.order_unit) + '</td>' +
          '<td class="num">' + (p.cost === null ? '未登録' : p.cost) + '</td><td>' + E(p.vendor_name || '') + '</td>' +
          '<td>' + (p.is_active ? '有効' : '無効') + '</td></tr>';
      }).join('') + '</tbody></table></div>';

    document.getElementById('add').onclick = async function () {
      const val = await UI.formDialog({
        title: '商品を追加',
        desc: '商品は必ず1つの担当ベンダーに紐づきます。',
        fields: [
          { name: 'own_code', label: '自社商品コード', required: true },
          { name: 'jan_code', label: 'JANコード', required: true },
          { name: 'name', label: '商品名', required: true },
          { name: 'category', label: '商品分類' },
          { name: 'spec', label: '規格' },
          { name: 'case_qty', label: 'ケース入数', type: 'number', value: 1, required: true, min: 1 },
          { name: 'order_unit', label: '発注単位', type: 'select', value: 'CASE',
            options: [{ value: 'CASE', label: 'ケース' }, { value: 'PIECE', label: 'バラ' }, { value: 'BOTH', label: 'ケース＋バラ' }] },
          { name: 'cost', label: '原価', type: 'number', min: 0 },
          { name: 'price', label: '売価', type: 'number', min: 0 },
          { name: 'vendor_id', label: '担当ベンダー', type: 'select', required: true,
            options: state.vendors.map(function (v) { return { value: v.id, label: v.name }; }) },
        ],
      });
      if (!val) return;
      val.vendor_id = parseInt(val.vendor_id, 10);
      val.allow_loose = val.order_unit !== 'CASE';
      try { await Api.post('/api/products', val); UI.toast('登録しました', 'ok'); renderView(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  async function renderUsers(body) {
    const rows = await Api.get('/api/users');
    body.innerHTML = '<button class="btn btn-primary btn-sm" id="add" style="margin-bottom:10px">＋ ユーザーを追加</button>' +
      rows.map(function (u) {
        return '<div class="card"><div class="card-head"><div>' +
          '<div class="card-title">' + E(u.name) + '</div>' +
          '<div class="card-sub">' + E(u.email) + ' / ' + E(u.role_label || '') +
            (u.store_name ? ' / ' + E(u.store_name) : '') + (u.vendor_name ? ' / ' + E(u.vendor_name) : '') + '</div>' +
          '<div class="card-sub">最終ログイン: ' + (u.last_login_at ? E(UI.fmtDateTime(u.last_login_at)) : '—') +
            ' / 失敗回数: ' + u.failed_login_count + (u.locked_until ? ' / <strong>ロック中</strong>' : '') + '</div>' +
          '</div>' + (u.is_active ? '<span class="badge ok">有効</span>' : '<span class="badge alert">停止</span>') + '</div>' +
          '<div class="card-actions">' +
            (u.locked_until ? '<button class="btn btn-sm" data-unlock="' + u.id + '">ロック解除</button>' : '') +
            (u.is_active ? '<button class="btn btn-sm btn-danger" data-suspend="' + u.id + '" data-name="' + E(u.name) + '">アカウント停止</button>' : '') +
          '</div></div>';
      }).join('');

    body.querySelectorAll('[data-unlock]').forEach(function (b) {
      b.onclick = async function () {
        try { await Api.post('/api/users/' + b.dataset.unlock + '/unlock'); UI.toast('ロックを解除しました', 'ok'); renderView(); }
        catch (err) { UI.toast(err.message, 'err'); }
      };
    });
    body.querySelectorAll('[data-suspend]').forEach(function (b) {
      b.onclick = async function () {
        const ok = await UI.confirmDialog({
          title: 'アカウントを停止しますか？',
          desc: '停止したユーザーはログインできなくなります。',
          rows: [{ k: 'ユーザー', v: b.dataset.name }], okLabel: '停止する', danger: true,
        });
        if (!ok) return;
        try { await Api.del('/api/users/' + b.dataset.suspend); UI.toast('停止しました', 'ok'); renderView(); }
        catch (err) { UI.toast(err.message, 'err'); }
      };
    });

    document.getElementById('add').onclick = async function () {
      const val = await UI.formDialog({
        title: 'ユーザーを追加',
        desc: '店舗担当者には店舗を、ベンダー担当者にはベンダーを必ず指定してください。',
        fields: [
          { name: 'name', label: '氏名', required: true },
          { name: 'email', label: 'メールアドレス', type: 'email', required: true },
          { name: 'password', label: '初期パスワード（8文字以上）', type: 'password', required: true },
          { name: 'role_code', label: '権限', type: 'select', required: true,
            options: Object.keys(state.meta.roles).map(function (k) { return { value: k, label: state.meta.roles[k] }; }) },
          { name: 'store_id', label: '店舗（店舗担当者のみ）', type: 'select',
            options: [{ value: '', label: '— なし —' }].concat(state.stores.map(function (s) { return { value: s.id, label: s.name }; })) },
          { name: 'vendor_id', label: 'ベンダー（ベンダー担当者のみ）', type: 'select',
            options: [{ value: '', label: '— なし —' }].concat(state.vendors.map(function (s) { return { value: s.id, label: s.name }; })) },
        ],
      });
      if (!val) return;
      val.store_id = val.store_id ? parseInt(val.store_id, 10) : null;
      val.vendor_id = val.vendor_id ? parseInt(val.vendor_id, 10) : null;
      try { await Api.post('/api/users', val); UI.toast('登録しました', 'ok'); renderView(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  async function renderDeadlines(body) {
    const rows = await Api.get('/api/deadlines');
    const scopeLabel = { SYSTEM: 'システム標準', VENDOR: 'ベンダー別', PRODUCT: '商品別' };
    body.innerHTML =
      '<div class="alert-box info">適用の優先順位は <strong>商品別 → ベンダー別 → システム標準</strong> です。</div>' +
      '<button class="btn btn-primary btn-sm" id="add" style="margin-bottom:10px">＋ 締め時間を追加</button>' +
      rows.map(function (d) {
        return '<div class="card"><div class="card-head">' +
          '<div class="card-title">' + E(scopeLabel[d.scope] || d.scope) + '</div>' +
          (d.is_active ? '<span class="badge ok">有効</span>' : '<span class="badge neutral">無効</span>') + '</div>' +
          '<div class="card-grid">' +
            '<div><div class="k">概算締め</div><div class="v">' + d.rough_days_before + '日前 ' + E(d.rough_time) + '</div></div>' +
            '<div><div class="k">最終締め</div><div class="v">' + d.final_days_before + '日前 ' + E(d.final_time) + '</div></div>' +
            '<div><div class="k">回答期限</div><div class="v">' + d.reply_days_before + '日前 ' + E(d.reply_time) + '</div></div>' +
            '<div><div class="k">対象</div><div class="v">' +
              (d.vendor_id ? 'ベンダーID ' + d.vendor_id : '') + (d.product_id ? ' 商品ID ' + d.product_id : '') +
              (!d.vendor_id && !d.product_id ? '全体' : '') + '</div></div>' +
          '</div>' + (d.note ? '<div class="card-sub" style="margin-top:6px">' + E(d.note) + '</div>' : '') + '</div>';
      }).join('');

    document.getElementById('add').onclick = async function () {
      const val = await UI.formDialog({
        title: '締め時間を追加',
        fields: [
          { name: 'scope', label: '適用範囲', type: 'select', required: true, value: 'VENDOR',
            options: [{ value: 'VENDOR', label: 'ベンダー別' }, { value: 'PRODUCT', label: '商品別' }] },
          { name: 'vendor_id', label: 'ベンダー', type: 'select',
            options: [{ value: '', label: '— なし —' }].concat(state.vendors.map(function (s) { return { value: s.id, label: s.name }; })) },
          { name: 'product_id', label: '商品ID（商品別の場合）', type: 'number', min: 1 },
          { name: 'rough_days_before', label: '概算締め（何日前）', type: 'number', value: 3, required: true, min: 0 },
          { name: 'rough_time', label: '概算締め時刻 (HH:MM)', value: '12:00', required: true },
          { name: 'final_days_before', label: '最終締め（何日前）', type: 'number', value: 1, required: true, min: 0 },
          { name: 'final_time', label: '最終締め時刻 (HH:MM)', value: '12:00', required: true },
          { name: 'reply_days_before', label: '回答期限（何日前）', type: 'number', value: 1, required: true, min: 0 },
          { name: 'reply_time', label: '回答期限時刻 (HH:MM)', value: '15:00', required: true },
        ],
      });
      if (!val) return;
      val.vendor_id = val.vendor_id ? parseInt(val.vendor_id, 10) : null;
      val.product_id = val.product_id || null;
      try { await Api.post('/api/deadlines', val); UI.toast('登録しました', 'ok'); renderView(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  async function renderReasons(body) {
    const rows = await Api.get('/api/reasons');
    const kinds = { CHANGE: '変更理由', SHORTAGE: '欠品理由' };
    body.innerHTML = '<button class="btn btn-primary btn-sm" id="add" style="margin-bottom:10px">＋ 理由を追加</button>' +
      Object.keys(kinds).map(function (k) {
        const items = rows.filter(function (r) { return r.kind === k; });
        return '<div class="section"><div class="section-title">' + E(kinds[k]) + '</div>' +
          (items.length ? items.map(function (r) {
            return '<div class="card"><div class="card-head"><div class="card-title">' + E(r.label) + '</div>' +
              '<span class="badge neutral">' + E(r.code) + '</span></div></div>';
          }).join('') : '<div class="empty">登録がありません</div>') + '</div>';
      }).join('');

    document.getElementById('add').onclick = async function () {
      const val = await UI.formDialog({
        title: '理由を追加',
        fields: [
          { name: 'kind', label: '種別', type: 'select', required: true, value: 'CHANGE',
            options: [{ value: 'CHANGE', label: '変更理由' }, { value: 'SHORTAGE', label: '欠品理由' }] },
          { name: 'code', label: 'コード', required: true },
          { name: 'label', label: '表示名', required: true },
        ],
      });
      if (!val) return;
      try { await Api.post('/api/reasons', val); UI.toast('登録しました', 'ok'); renderView(); }
      catch (err) { UI.toast(err.message, 'err'); }
    };
  }

  /* ==================================================================
     リアルタイム反映（ポーリング）
     ================================================================== */
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(async function () {
      if (!state.me || document.hidden) return;
      // 入力中・モーダル表示中は画面を作り直さない
      if (UI.isDirty() || document.getElementById('modal-root').innerHTML) { refreshUnread(); return; }
      const refreshable = ['dashboard', 'orders', 'vendor-orders', 'change-requests', 'notifications'];
      if (refreshable.indexOf(state.view) >= 0) {
        try { await renderView(); } catch (e) { /* 一時的な通信断は無視 */ }
      }
      refreshUnread();
    }, 20000);
  }

  function stopPolling() {
    if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  boot();
})();
