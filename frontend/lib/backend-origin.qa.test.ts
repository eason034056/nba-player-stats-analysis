import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { describe, expect, it } from "vitest";

const require = createRequire(import.meta.url);
const { resolveBackendOrigin, LOCAL_BACKEND_ORIGIN } = require("./backend-origin");

const local = {} as Record<string, string | undefined>;
const vercelProd = { VERCEL: "1", VERCEL_ENV: "production" };
const vercelPreview = { VERCEL: "1", VERCEL_ENV: "preview" };

function errorOf(env: Record<string, string | undefined>): string {
  try {
    resolveBackendOrigin(env);
  } catch (error) {
    return (error as Error).message;
  }
  throw new Error("expected resolveBackendOrigin to throw");
}

describe("QA: BACKEND_API_URL normalization", () => {
  it("strips a trailing slash, lowercases the host, and keeps a port", () => {
    expect(resolveBackendOrigin({ ...vercelProd, BACKEND_API_URL: "https://API.Example.com/" })).toBe(
      "https://api.example.com",
    );
    expect(resolveBackendOrigin({ ...vercelProd, BACKEND_API_URL: "  https://api.example.com:8443  " })).toBe(
      "https://api.example.com:8443",
    );
  });

  it("rejects a query, a hash, a path, credentials, quotes, and a non-http scheme", () => {
    for (const value of [
      "https://api.example.com/?a=1",
      "https://api.example.com/#x",
      "https://api.example.com/api/",
      "https://user:pw@api.example.com",
      '"https://api.example.com"',
      "'https://api.example.com'",
      "ftp://api.example.com",
    ]) {
      expect(() => resolveBackendOrigin({ ...vercelPreview, BACKEND_API_URL: value })).toThrow(/BACKEND_API_URL/);
    }
  });

  it("treats empty VERCEL and VERCEL_ENV as a local build", () => {
    expect(resolveBackendOrigin({ VERCEL: "", VERCEL_ENV: " ", BACKEND_API_URL: "" })).toBe(LOCAL_BACKEND_ORIGIN);
    expect(resolveBackendOrigin(local)).toBe("http://localhost:8000");
  });

});

describe("QA: build errors do not print the configured value", () => {
  // A Vercel build log is visible to everyone on the project. A mistyped value
  // can still carry a real host or a key, so the error names the rule only.
  it.each([
    "api.internal.example.net?key=SECRET123",
    "not a url SECRET123",
    "https://user:SECRET123@api.example.com",
    "https://api.example.com/SECRET123",
    "https://api.example.com/?token=SECRET123",
    "gopher://SECRET123.example.com",
  ])("does not echo %s", (value) => {
    const message = errorOf({ ...vercelProd, BACKEND_API_URL: value });
    expect(message).toMatch(/BACKEND_API_URL/);
    expect(message).not.toContain("SECRET123");
    expect(message).not.toContain(value);
  });
});

describe("QA: a Vercel build needs an https origin", () => {
  it("rejects http on Vercel Production and Preview builds without echoing the host", () => {
    for (const env of [vercelProd, vercelPreview, { VERCEL: "1" }]) {
      const message = errorOf({ ...env, BACKEND_API_URL: "http://api.internal-host.example.net" });
      expect(message).toMatch(/https/);
      expect(message).not.toContain("internal-host");
    }
  });

  it("keeps http for a local build", () => {
    expect(resolveBackendOrigin({ BACKEND_API_URL: "http://127.0.0.1:8000" })).toBe("http://127.0.0.1:8000");
  });
});

describe("QA: the backend origin stays out of client modules", () => {
  const read = (file: string) => readFileSync(path.join(__dirname, file), "utf8");

  it("browser-api-prefix.js reads no environment variable", () => {
    expect(read("browser-api-prefix.js")).not.toMatch(/process\.env/);
  });

  it("api.ts does not import backend-origin or read BACKEND_API_URL / NEXT_PUBLIC_API_URL", () => {
    const source = read("api.ts");
    expect(source).not.toMatch(/backend-origin/);
    expect(source).not.toMatch(/process\.env\.(BACKEND_API_URL|NEXT_PUBLIC_API_URL)/);
    expect(source).toMatch(/from "\.\/browser-api-prefix"/);
  });
});
