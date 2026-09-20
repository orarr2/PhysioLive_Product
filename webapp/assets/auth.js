/**
 * Client-side auth for PhysioLive.
 *
 * The user must sign in before any VM call. Two routes:
 *   - Google Sign-In: opens Google Identity Services, receives an
 *     ID token, sends it to the VM's `/auth/google`, receives back a
 *     signed JWT used as the Bearer for all subsequent calls.
 *   - Passphrase: user pastes a shared passphrase into a modal input,
 *     the client sends it to `/auth/login` and receives the same
 *     shape of JWT back.
 *
 * The JWT lives in localStorage under `physiolive.jwt` and expires
 * after 7 days by default (server-controlled). The last known profile
 * (email, name, picture, source) lives under `physiolive.profile`.
 *
 * There is no anonymous / guest route.
 */

import { CONFIG, resolveVmOrigin, getResolvedVmOrigin } from "./config.js";

const JWT_KEY = "physiolive.jwt";
const JWT_EXP_KEY = "physiolive.jwt_exp";
const PROFILE_KEY = "physiolive.profile";

// -------------------------------------------------------------- state

export function getStoredJwt() {
  try {
    const jwt = localStorage.getItem(JWT_KEY);
    const exp = Number(localStorage.getItem(JWT_EXP_KEY) || 0);
    if (!jwt) return null;
    if (exp && Date.now() / 1000 > exp) {
      clearAuth();
      return null;
    }
    return jwt;
  } catch (_) {
    return null;
  }
}

export function getSavedProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

export function currentUserId() {
  const profile = getSavedProfile();
  return (profile && (profile.sub || profile.email)) || null;
}

export function isSignedIn() {
  return !!getStoredJwt();
}

export function authHeader() {
  const jwt = getStoredJwt();
  return jwt ? { Authorization: `Bearer ${jwt}` } : {};
}

export function signOut() {
  clearAuth();
}

function clearAuth() {
  try {
    localStorage.removeItem(JWT_KEY);
    localStorage.removeItem(JWT_EXP_KEY);
    localStorage.removeItem(PROFILE_KEY);
  } catch (_) { /* ignore */ }
}

function saveAuth(jwt, exp, profile) {
  try {
    localStorage.setItem(JWT_KEY, jwt);
    if (exp) localStorage.setItem(JWT_EXP_KEY, String(exp));
    if (profile) localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
  } catch (_) { /* private mode */ }
}

// -------------------------------------------------------------- server

/**
 * Exchange a Google ID token for a PhysioLive JWT. Returns the
 * profile object on success; throws on rejection so the caller can
 * show a clear error.
 */
export async function signInWithGoogleToken(idToken) {
  await resolveVmOrigin();
  const origin = getResolvedVmOrigin();
  const res = await fetch(`${origin}/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token: idToken }),
  });
  if (!res.ok) {
    const detail = await _errorDetail(res);
    throw new Error(detail || `Google sign-in rejected (${res.status})`);
  }
  const data = await res.json();
  saveAuth(data.jwt, data.exp, data.profile);
  return data.profile;
}

/**
 * Exchange a shared passphrase for a PhysioLive JWT.
 */
export async function signInWithPassphrase(passphrase, displayName) {
  await resolveVmOrigin();
  const origin = getResolvedVmOrigin();
  const res = await fetch(`${origin}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      passphrase: passphrase,
      display_name: displayName || "",
    }),
  });
  if (!res.ok) {
    const detail = await _errorDetail(res);
    throw new Error(detail || `Passphrase rejected (${res.status})`);
  }
  const data = await res.json();
  saveAuth(data.jwt, data.exp, data.profile);
  return data.profile;
}

async function _errorDetail(res) {
  try {
    const body = await res.json();
    return body.detail || body.error || null;
  } catch (_) { return null; }
}

// -------------------------------------------------------------- google sdk

let _googleReady = null;
function loadGoogleScript() {
  if (_googleReady) return _googleReady;
  _googleReady = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.onload = () => resolve(window.google);
    s.onerror = reject;
    document.head.appendChild(s);
  });
  return _googleReady;
}

/**
 * Render a Google sign-in button into `container`. Resolves when the
 * user completes the flow with a profile, or rejects on failure.
 * When `CONFIG.googleClientId` is null this resolves immediately with
 * null so the caller can hide the Google row.
 */
export async function renderGoogleButton(container) {
  if (!CONFIG.googleClientId) return null;
  await loadGoogleScript();
  return new Promise((resolve, reject) => {
    window.google.accounts.id.initialize({
      client_id: CONFIG.googleClientId,
      callback: async (response) => {
        try {
          const profile = await signInWithGoogleToken(response.credential);
          resolve(profile);
        } catch (e) { reject(e); }
      },
    });
    window.google.accounts.id.renderButton(container, {
      theme: "filled_black",
      size: "large",
      shape: "pill",
      text: "signin_with",
      width: 260,
    });
  });
}
