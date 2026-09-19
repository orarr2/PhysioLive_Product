/**
 * Google Identity Services (Sign-In with Google) wrapper.
 *
 * The web app reads a Google client id from `assets/config.js`. When
 * the id is present, `promptSignIn()` opens the Google Sign-In flow,
 * decodes the returned ID token and hands the caller a lightweight
 * profile ({sub, email, name, picture}). Anonymous users still get a
 * stable UUID stored in localStorage under `physiolive.anon_id`.
 */

import { CONFIG } from "./config.js";

const ANON_KEY = "physiolive.anon_id";
const PROFILE_KEY = "physiolive.profile";
const TOKEN_KEY = "physiolive.id_token";

export function currentUserId() {
  const profile = getSavedProfile();
  if (profile && profile.sub) return profile.sub;
  return getOrCreateAnonId();
}

export function getSavedProfile() {
  try {
    const raw = localStorage.getItem(PROFILE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_) {
    return null;
  }
}

export function signOut() {
  try {
    localStorage.removeItem(PROFILE_KEY);
    localStorage.removeItem(TOKEN_KEY);
  } catch (_) { /* ignore */ }
}

export function getOrCreateAnonId() {
  try {
    let id = localStorage.getItem(ANON_KEY);
    if (!id) {
      id = _uuid();
      localStorage.setItem(ANON_KEY, id);
    }
    return id;
  } catch (_) {
    return "anon";
  }
}

export async function promptSignIn(container) {
  if (!CONFIG.googleClientId) {
    console.warn("googleClientId not configured; signIn disabled");
    return null;
  }
  await _loadGoogleScript();
  return new Promise((resolve) => {
    window.google.accounts.id.initialize({
      client_id: CONFIG.googleClientId,
      callback: (response) => {
        const profile = _decodeIdToken(response.credential);
        if (profile) {
          try {
            localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
            localStorage.setItem(TOKEN_KEY, response.credential);
          } catch (_) { /* private mode */ }
        }
        resolve(profile);
      },
    });
    window.google.accounts.id.renderButton(container, {
      theme: "filled_black",
      size: "large",
      shape: "pill",
    });
    window.google.accounts.id.prompt();
  });
}

function _loadGoogleScript() {
  if (window.google && window.google.accounts) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

function _decodeIdToken(token) {
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    const obj = JSON.parse(json);
    return {
      sub: obj.sub, email: obj.email, name: obj.name, picture: obj.picture,
    };
  } catch (_) {
    return null;
  }
}

function _uuid() {
  if (crypto && crypto.randomUUID) return crypto.randomUUID();
  return "xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
