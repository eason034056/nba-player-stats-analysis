/**
 * proxy-request.js
 *
 * Builds the external rewrite for /api/backend/* and the headers that
 * ride with it. next.config.js calls assertVercelHostingEnv at build
 * time. middleware.ts calls prepareProxiedRequest on each request.
 * The proxy secret is never written into an error message.
 */

const { BROWSER_API_PREFIX } = require("./browser-api-prefix");
const { isVercelBuild, resolveBackendOrigin } = require("./backend-origin");

const PROXY_SECRET_HEADER = "x-sportslab-proxy-secret";
const REAL_IP_HEADER = "x-real-ip";
const FORWARDED_FOR_HEADER = "x-forwarded-for";
const VERCEL_FORWARDED_FOR_HEADER = "x-vercel-forwarded-for";

const PROXY_NOT_CONFIGURED = "The API proxy is not configured.";

function readProxySecret(env) {
  return typeof env.VERCEL_PROXY_SECRET === "string" ? env.VERCEL_PROXY_SECRET.trim() : "";
}

function assertProxySecret(env = process.env) {
  if (isVercelBuild(env) && !readProxySecret(env)) {
    throw new Error(
      "VERCEL_PROXY_SECRET is required when VERCEL or VERCEL_ENV is set. " +
        "Set it in the Vercel Production and Preview environments, then redeploy. " +
        "This build will not continue without a proxy secret.",
    );
  }
}

function assertVercelHostingEnv(env = process.env) {
  resolveBackendOrigin(env);
  assertProxySecret(env);
}

function firstIp(value) {
  if (typeof value !== "string") {
    return "";
  }
  const first = value.split(",")[0].trim();
  return first;
}

function clientIpFromHeaders(headers) {
  // x-real-ip is not read here. The browser can set it, and the
  // caller replaces it. x-vercel-forwarded-for is Vercel's own copy.
  // x-forwarded-for is the visitor IP after Vercel overwrites the
  // client-supplied value.
  const vercelIp = firstIp(headers.get(VERCEL_FORWARDED_FOR_HEADER));
  if (vercelIp) {
    return vercelIp;
  }
  return firstIp(headers.get(FORWARDED_FOR_HEADER));
}

function prepareProxiedRequest({ pathname, search = "", headers, env = process.env }) {
  let origin;
  try {
    origin = resolveBackendOrigin(env);
  } catch {
    return { ok: false, status: 500, message: PROXY_NOT_CONFIGURED };
  }

  const secret = readProxySecret(env);
  if (isVercelBuild(env) && !secret) {
    return { ok: false, status: 500, message: PROXY_NOT_CONFIGURED };
  }

  if (!pathname.startsWith(`${BROWSER_API_PREFIX}/`) && pathname !== BROWSER_API_PREFIX) {
    return { ok: false, status: 500, message: PROXY_NOT_CONFIGURED };
  }

  const rest = pathname.slice(BROWSER_API_PREFIX.length) || "/";
  if (rest.startsWith("//") || rest.includes("\\")) {
    return { ok: false, status: 400, message: PROXY_NOT_CONFIGURED };
  }
  const destination = new URL(`${rest}${search}`, origin);
  if (destination.origin !== new URL(origin).origin) {
    return { ok: false, status: 400, message: PROXY_NOT_CONFIGURED };
  }
  const ip = clientIpFromHeaders(headers);
  const nextHeaders = new Headers(headers);
  nextHeaders.delete(PROXY_SECRET_HEADER);
  nextHeaders.delete(REAL_IP_HEADER);
  if (secret) {
    nextHeaders.set(PROXY_SECRET_HEADER, secret);
  }
  if (ip) {
    nextHeaders.set(REAL_IP_HEADER, ip);
    nextHeaders.set(FORWARDED_FOR_HEADER, ip);
  } else {
    nextHeaders.delete(FORWARDED_FOR_HEADER);
  }

  return { ok: true, destination, headers: nextHeaders };
}

module.exports = {
  PROXY_SECRET_HEADER,
  REAL_IP_HEADER,
  FORWARDED_FOR_HEADER,
  PROXY_NOT_CONFIGURED,
  assertProxySecret,
  assertVercelHostingEnv,
  prepareProxiedRequest,
};
