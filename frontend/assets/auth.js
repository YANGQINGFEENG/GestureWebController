/**
 * 前端登录态与接口封装（演示页与个人中心共用）。
 *
 * token 存 localStorage：演示阶段够用；正式接入第三方页面时应改成
 * 由宿主页面注入（SDK 支持 token 传函数），避免跨站共享存储。
 */

const TOKEN_KEY = 'gwc_token';
const USER_KEY = 'gwc_user';
const ENDPOINT_KEY = 'gwc_endpoint';

export const DEFAULT_ENDPOINT = 'http://127.0.0.1:8000';

export function getEndpoint() {
  return (localStorage.getItem(ENDPOINT_KEY) || DEFAULT_ENDPOINT).replace(/\/+$/, '');
}

export function setEndpoint(url) {
  localStorage.setItem(ENDPOINT_KEY, String(url || DEFAULT_ENDPOINT).replace(/\/+$/, ''));
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null');
  } catch {
    return null;
  }
}

export function saveSession(payload) {
  if (payload?.access_token) localStorage.setItem(TOKEN_KEY, payload.access_token);
  if (payload?.user) localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** 统一请求：自动带 token、自动解析 JSON、把后端 detail 变成可读错误。 */
export async function api(path, { method = 'GET', body, auth = true, endpoint } = {}) {
  const base = (endpoint || getEndpoint()).replace(/\/+$/, '');
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    if (res.status === 401 && auth) clearSession(); // token 失效自动登出，避免页面一直报错
    const detail = data?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg || d.type).join('；')
          : `请求失败（HTTP ${res.status}）`;
    const error = new Error(message);
    error.status = res.status;
    error.data = data;
    throw error;
  }
  return data;
}
