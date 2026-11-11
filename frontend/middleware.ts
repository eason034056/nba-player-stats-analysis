import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { prepareProxiedRequest } from "./lib/proxy-request";

export function middleware(request: NextRequest) {
  const prepared = prepareProxiedRequest({
    pathname: request.nextUrl.pathname,
    search: request.nextUrl.search,
    headers: request.headers,
    env: {
      VERCEL: process.env.VERCEL,
      VERCEL_ENV: process.env.VERCEL_ENV,
      BACKEND_API_URL: process.env.BACKEND_API_URL,
      VERCEL_PROXY_SECRET: process.env.VERCEL_PROXY_SECRET,
    },
  });

  if (!prepared.ok) {
    return new NextResponse(prepared.message, {
      status: prepared.status,
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  }

  return NextResponse.rewrite(prepared.destination, {
    request: { headers: prepared.headers },
  });
}

export const config = {
  matcher: "/api/backend/:path*",
};
