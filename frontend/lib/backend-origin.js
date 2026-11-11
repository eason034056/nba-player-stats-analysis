/**
 * backend-origin.js
 *
 * Resolves the backend origin for the /api/backend proxy.
 * proxy-request.js is the application importer. Client code must not
 * import this file: BACKEND_API_URL is server-only.
 *
 * Local `next dev` and `next build` (VERCEL and VERCEL_ENV unset) use
 * http://localhost:8000 when BACKEND_API_URL is empty. A Vercel build
 * sets one of those variables and must fail instead of using localhost.
 */

const LOCAL_BACKEND_ORIGIN = "http://localhost:8000";

function isVercelBuild(env) {
  return hasText(env.VERCEL) || hasText(env.VERCEL_ENV);
}

function hasText(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function resolveBackendOrigin(env = process.env) {
  const raw = typeof env.BACKEND_API_URL === "string" ? env.BACKEND_API_URL.trim() : "";

  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    throw new Error(
      "BACKEND_API_URL must not be wrapped in quotes. Paste the origin only, for example https://api.example.com.",
    );
  }

  if (raw) {
    const origin = normalizeBackendOrigin(raw);
    if (isVercelBuild(env) && !origin.startsWith("https://")) {
      throw new Error("BACKEND_API_URL must use https on a Vercel build.");
    }
    return origin;
  }

  if (isVercelBuild(env)) {
    throw new Error(
      "BACKEND_API_URL is required when VERCEL or VERCEL_ENV is set. " +
        "Set BACKEND_API_URL to the backend origin (for example https://api.example.com) " +
        "in the Vercel Production and Preview environments, then redeploy. " +
        `This build will not fall back to ${LOCAL_BACKEND_ORIGIN}.`,
    );
  }

  return LOCAL_BACKEND_ORIGIN;
}

function normalizeBackendOrigin(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(
      "BACKEND_API_URL must be an absolute http(s) origin, for example https://api.example.com.",
    );
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(
      `BACKEND_API_URL must use http or https. Received protocol: ${url.protocol}`,
    );
  }

  if (url.username || url.password) {
    throw new Error("BACKEND_API_URL must not include a username or password.");
  }

  if (url.search || url.hash) {
    throw new Error("BACKEND_API_URL must not include a query string or hash.");
  }

  if (url.pathname !== "/" && url.pathname !== "") {
    throw new Error(
      "BACKEND_API_URL must be an origin with no path. The rewrite appends the request path itself.",
    );
  }

  return `${url.protocol}//${url.host}`;
}

module.exports = {
  LOCAL_BACKEND_ORIGIN,
  isVercelBuild,
  resolveBackendOrigin,
};
