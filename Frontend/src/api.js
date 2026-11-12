// api.js
// Every call to the backend goes through apiFetch.
//
// Sessions: the access token lives only in memory here (never in localStorage)
// and lasts about 15 minutes. The refresh token is an httpOnly cookie that this
// code cannot read; the browser sends it to /auth/refresh, which returns a new
// access token. So when a request comes back 401, apiFetch refreshes once and
// repeats the request, and the user never notices the token expiring.
import { API } from './config';

let accessToken = null;
let refreshing = null;   // the refresh in progress, shared by everything that needs one

export const setAccessToken = (token) => { accessToken = token || null; };

async function requestRefresh() {
  const res = await fetch(`${API}/auth/refresh`, { method: 'POST', credentials: 'include' });
  if (!res.ok) {
    accessToken = null;
    return null;
  }
  const data = await res.json();
  accessToken = data.access_token;
  return data;           // { access_token, role, expires_in }
}

// Returns the new session, or null when the user has to sign in again.
export function refreshSession() {
  if (!refreshing) {
    const run = () => requestRefresh().catch(() => null);
    // Web Locks make tabs take turns, so two tabs do not spend the same cookie at once
    const result = navigator.locks?.request
      ? navigator.locks.request('docmind-refresh', run)
      : run();
    refreshing = Promise.resolve(result).finally(() => { refreshing = null; });
  }
  return refreshing;
}

// A 401 from these means "wrong password" or "no session", not "token expired"
const NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout'];

export async function apiFetch(url, options = {}) {
  const send = () => fetch(url, {
    ...options,
    credentials: 'include',   // lets the browser store and send the refresh cookie
    headers: {
      ...(options.headers || {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });

  let res = await send();
  if (res.status === 401 && !NO_REFRESH.some(path => url.includes(path))) {
    if (await refreshSession()) res = await send();
  }
  return res;
}

// Ends the session on the server (the refresh token is revoked), best effort
export async function signOut() {
  accessToken = null;
  try {
    await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' });
  } catch { /* offline: the cookie simply expires on its own */ }
}
