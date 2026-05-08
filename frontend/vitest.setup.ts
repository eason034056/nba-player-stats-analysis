import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

vi.mock("next/image", () => ({
  default: ({
    alt,
    src,
    priority: _priority,
    unoptimized: _unoptimized,
    ...props
  }: React.ImgHTMLAttributes<HTMLImageElement> & {
    src: string;
    priority?: boolean;
    unoptimized?: boolean;
  }) =>
    React.createElement("img", { alt, src, ...props }),
}));

afterEach(() => {
  cleanup();
});

// 💡 Guard for tests using `// @vitest-environment node` — those have no
// window/HTMLElement and don't need any of these jsdom polyfills.
if (typeof window !== "undefined") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  vi.stubGlobal("ResizeObserver", ResizeObserverMock);

  HTMLElement.prototype.scrollIntoView = vi.fn();
}
