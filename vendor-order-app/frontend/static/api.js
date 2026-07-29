/* API 通信層。
   - Cookie セッション + CSRF トークン（double submit）を扱う。
   - 通信失敗と権限エラーを画面に出せる形で投げ直す。
*/
(function (global) {
  'use strict';

  function getCookie(name) {
    const m = document.cookie.match(new RegExp('(^|;\\s*)' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[2]) : null;
  }

  class ApiError extends Error {
    constructor(status, message, payload) {
      super(message);
      this.status = status;
      this.payload = payload;
    }
    get isForbidden() { return this.status === 403; }
    get isUnauthorized() { return this.status === 401; }
    get isConflict() { return this.status === 409; }
  }

  async function request(method, path, body, options) {
    options = options || {};
    const headers = {};
    if (body !== undefined && body !== null) headers['Content-Type'] = 'application/json';
    if (method !== 'GET' && method !== 'HEAD') {
      const csrf = getCookie('csrf_token');
      if (csrf) headers['X-CSRF-Token'] = csrf;
    }

    let res;
    try {
      res = await fetch(path, {
        method,
        headers,
        credentials: 'same-origin',
        body: body === undefined || body === null ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      // 通信失敗（圏外・電波不良）を明示的に伝える
      throw new ApiError(0, '通信に失敗しました。電波状況を確認してもう一度お試しください。', null);
    }

    if (options.raw) {
      if (!res.ok) throw new ApiError(res.status, await safeMessage(res), null);
      return res;
    }

    if (res.status === 204) return null;

    let payload = null;
    const ct = res.headers.get('Content-Type') || '';
    if (ct.includes('application/json')) {
      payload = await res.json().catch(function () { return null; });
    } else {
      payload = await res.text().catch(function () { return null; });
    }

    if (!res.ok) {
      throw new ApiError(res.status, extractMessage(payload, res.status), payload);
    }
    return payload;
  }

  async function safeMessage(res) {
    try {
      const data = await res.json();
      return extractMessage(data, res.status);
    } catch (e) {
      return 'エラーが発生しました（' + res.status + '）';
    }
  }

  function extractMessage(payload, status) {
    if (payload && typeof payload === 'object') {
      const d = payload.detail;
      if (typeof d === 'string') return d;
      if (d && typeof d === 'object' && d.message) return d.message;
      if (Array.isArray(payload.errors) && payload.errors.length) {
        return (payload.detail || '入力エラー') + '：' + payload.errors.join(' / ');
      }
      if (typeof payload.detail !== 'undefined') return JSON.stringify(payload.detail);
    }
    if (status === 401) return 'ログインが必要です。';
    if (status === 403) return 'この操作を行う権限がありません。';
    if (status === 404) return '対象が見つかりません。';
    return 'エラーが発生しました（' + status + '）';
  }

  function qs(params) {
    const usp = new URLSearchParams();
    Object.keys(params || {}).forEach(function (k) {
      const v = params[k];
      if (v !== undefined && v !== null && v !== '') usp.append(k, v);
    });
    const s = usp.toString();
    return s ? '?' + s : '';
  }

  const Api = {
    ApiError: ApiError,
    qs: qs,
    get: function (path, params) { return request('GET', path + qs(params)); },
    post: function (path, body) { return request('POST', path, body === undefined ? {} : body); },
    put: function (path, body) { return request('PUT', path, body); },
    del: function (path, params) { return request('DELETE', path + qs(params)); },

    // --- 認証 ---
    login: function (email, password) { return request('POST', '/api/auth/login', { email: email, password: password }); },
    logout: function () { return request('POST', '/api/auth/logout', {}); },
    me: function () { return request('GET', '/api/auth/me'); },
    requestPasswordReset: function (email) { return request('POST', '/api/auth/password-reset/request', { email: email }); },
    confirmPasswordReset: function (token, pw) { return request('POST', '/api/auth/password-reset/confirm', { token: token, new_password: pw }); },

    // --- ダウンロード（権限は必ずサーバー側で判定される） ---
    download: async function (path, params) {
      const url = path + qs(params);
      const res = await request('GET', url, null, { raw: true });
      const ct = res.headers.get('Content-Type') || '';
      if (ct.includes('text/html')) {
        // 印刷用PDF: 新しいタブで開き、ブラウザの印刷からPDF保存する
        const html = await res.text();
        const w = window.open('', '_blank');
        if (!w) throw new ApiError(0, 'ポップアップがブロックされました。ブラウザの設定を確認してください。', null);
        w.document.write(html);
        w.document.close();
        return;
      }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const match = cd.match(/filename="?([^"]+)"?/);
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = match ? match[1] : 'download';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(function () { URL.revokeObjectURL(link.href); }, 2000);
    },

    newToken: function () {
      // 二重送信防止トークン
      if (global.crypto && global.crypto.randomUUID) return global.crypto.randomUUID();
      return 'tok-' + Date.now() + '-' + Math.random().toString(36).slice(2, 10);
    },
  };

  global.Api = Api;
})(window);
