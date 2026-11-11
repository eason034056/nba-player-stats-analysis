/**
 * browser-api-prefix.js
 *
 * The path the browser requests. It is same-origin and has no host.
 * middleware.ts proxies `/api/backend/:path*` onto BACKEND_API_URL.
 * This file must not read environment variables: client components
 * import it, and a server-only value here would be in the wrong module.
 */

const BROWSER_API_PREFIX = "/api/backend";

module.exports = {
  BROWSER_API_PREFIX,
};
