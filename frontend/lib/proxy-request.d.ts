export const PROXY_SECRET_HEADER: string;
export const REAL_IP_HEADER: string;
export const FORWARDED_FOR_HEADER: string;
export const PROXY_NOT_CONFIGURED: string;

export type ProxyEnv = {
  VERCEL?: string;
  VERCEL_ENV?: string;
  BACKEND_API_URL?: string;
  VERCEL_PROXY_SECRET?: string;
};

export function assertProxySecret(env?: ProxyEnv): void;
export function assertVercelHostingEnv(env?: ProxyEnv): void;

export function prepareProxiedRequest(input: {
  pathname: string;
  search?: string;
  headers: Headers;
  env?: ProxyEnv;
}):
  | { ok: true; destination: URL; headers: Headers }
  | { ok: false; status: number; message: string };
