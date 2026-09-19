/**
 * Runtime configuration read by the web app. Update this file when
 * the PhysioLive VM comes online.
 */

export const CONFIG = {
  // Origin of the PhysioLive coach + RAG service. Leave as null while
  // the VM is offline; the web app falls back to rule-only feedback.
  vmOrigin: null,

  // Google Sign-In client id. Create one at
  // https://console.cloud.google.com/apis/credentials
  // under "OAuth 2.0 Client IDs" and paste the value here.
  googleClientId: null,
};
