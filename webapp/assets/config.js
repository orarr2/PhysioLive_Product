/**
 * Runtime configuration read by the web app. Update this file when
 * the PhysioLive VM comes online.
 */

export const CONFIG = {
  // Origin of the PhysioLive coach + RAG service.
  // Currently a Cloudflare TryCloudflare URL - it will change every
  // time the tunnel restarts. When the operator moves to a named
  // tunnel with a stable hostname, replace this value.
  vmOrigin: "https://butter-several-publisher-lance.trycloudflare.com",

  // Google Sign-In client id. Create one at
  // https://console.cloud.google.com/apis/credentials
  // under "OAuth 2.0 Client IDs" and paste the value here.
  googleClientId: null,

  // Bearer token expected by the VM's /rag/query and /coach/feedback
  // endpoints. Must match PHYSIOLIVE_API_TOKEN on the VM. Not a
  // user-specific secret - it is the shared gate that lets every
  // browser client talk to the shared coach service.
  apiToken: "-cXesXlAii8XMi75lgOjXx_sGdY1FpaMMIy3gzQiEII",
};
