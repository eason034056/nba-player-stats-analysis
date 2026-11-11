import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const {
  LOCAL_BACKEND_ORIGIN,
  resolveBackendOrigin,
  buildBackendRewrite,
} = require("./backend-origin");

const localEnv = { VERCEL: undefined, VERCEL_ENV: undefined };
const vercelEnv = { VERCEL: "1", VERCEL_ENV: "production" };

describe("backend origin", () => {
  it("normalizes trailing slash, host case, port, and surrounding whitespace", () => {
    expect(
      resolveBackendOrigin({
        ...localEnv,
        BACKEND_API_URL: "  HTTPS://API.Example.COM:8443/  ",
      }),
    ).toBe("https://api.example.com:8443");
  });

  it("rejects query, hash, path, userinfo, quotes, and a non-http scheme", () => {
    const rejected = [
      "https://api.example.com?x=1",
      "https://api.example.com#frag",
      "https://api.example.com/api",
      "https://user:pass@api.example.com",
      '"https://api.example.com"',
      "ftp://api.example.com",
    ];
    for (const value of rejected) {
      expect(() => resolveBackendOrigin({ ...localEnv, BACKEND_API_URL: value })).toThrow();
    }
  });

  it("treats an empty VERCEL or VERCEL_ENV as a local build", () => {
    expect(resolveBackendOrigin({ VERCEL: "", VERCEL_ENV: "   ", BACKEND_API_URL: "" })).toBe(
      LOCAL_BACKEND_ORIGIN,
    );
    expect(resolveBackendOrigin({ VERCEL: "  ", VERCEL_ENV: "", BACKEND_API_URL: undefined })).toBe(
      LOCAL_BACKEND_ORIGIN,
    );
  });

  it("builds the rewrite source and destination", () => {
    expect(buildBackendRewrite({ ...localEnv, BACKEND_API_URL: undefined })).toEqual({
      source: "/api/backend/:path*",
      destination: "http://localhost:8000/:path*",
    });
    expect(
      buildBackendRewrite({ ...vercelEnv, BACKEND_API_URL: "https://api.example.com/" }),
    ).toEqual({
      source: "/api/backend/:path*",
      destination: "https://api.example.com/:path*",
    });
  });

  it("does not include the configured value in an invalid-origin error", () => {
    const inputs = [
      "not a url ?key=SECRET123",
      "http://bad host",
      "://missing",
      "totally-not-a-url",
      "not a url ?key=VERCEL_PROXY_SECRET",
      "%%%",
    ];
    for (const value of inputs) {
      let message = "";
      try {
        resolveBackendOrigin({ ...vercelEnv, BACKEND_API_URL: value });
      } catch (error) {
        message = error instanceof Error ? error.message : String(error);
      }
      expect(message.length).toBeGreaterThan(0);
      expect(message).not.toContain(value.trim());
      expect(message).not.toContain("Received:");
      expect(message).not.toContain("SECRET123");
    }
  });

  it("rejects http on a Vercel build and allows http locally", () => {
    expect(() =>
      resolveBackendOrigin({ ...vercelEnv, BACKEND_API_URL: "http://api.example.com" }),
    ).toThrow("BACKEND_API_URL must use https on a Vercel build.");

    let message = "";
    try {
      resolveBackendOrigin({ ...vercelEnv, BACKEND_API_URL: "http://secret-host.example" });
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    }
    expect(message).not.toContain("secret-host.example");

    expect(
      resolveBackendOrigin({ ...localEnv, BACKEND_API_URL: "http://10.0.0.8:8000" }),
    ).toBe("http://10.0.0.8:8000");
    expect(resolveBackendOrigin({ ...localEnv, BACKEND_API_URL: undefined })).toBe(
      "http://localhost:8000",
    );
  });

  it("does not let the client module read the server origin", () => {
    const prefix = readFileSync(join(process.cwd(), "lib/browser-api-prefix.js"), "utf8");
    const api = readFileSync(join(process.cwd(), "lib/api.ts"), "utf8");
    expect(prefix).not.toContain("process.env");
    expect(api).not.toContain("backend-origin");
    expect(api).not.toContain("process.env.BACKEND_API_URL");
    expect(api).not.toContain("process.env.NEXT_PUBLIC_API_URL");
    expect(api).not.toContain("process.env.VERCEL_PROXY_SECRET");
  });
});
