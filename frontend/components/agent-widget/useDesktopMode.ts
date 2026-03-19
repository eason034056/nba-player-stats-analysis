"use client";

import { useEffect, useState } from "react";

const DESKTOP_QUERY = "(min-width: 1024px)";

export const useDesktopMode = () => {
  const [isDesktop, setIsDesktop] = useState(() => {
    if (typeof window === "undefined") {
      return false;
    }

    return window.matchMedia(DESKTOP_QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined") {
      return undefined;
    }

    const mediaQuery = window.matchMedia(DESKTOP_QUERY);
    const legacyMediaQuery = mediaQuery as MediaQueryList & {
      addListener?: (listener: (event: MediaQueryListEvent) => void) => void;
      removeListener?: (listener: (event: MediaQueryListEvent) => void) => void;
    };
    const updateDesktopMode = (event?: MediaQueryListEvent) => {
      setIsDesktop(event?.matches ?? mediaQuery.matches);
    };

    updateDesktopMode();

    if ("addEventListener" in mediaQuery) {
      mediaQuery.addEventListener("change", updateDesktopMode);
      return () => mediaQuery.removeEventListener("change", updateDesktopMode);
    }

    legacyMediaQuery.addListener?.(updateDesktopMode);
    return () => legacyMediaQuery.removeListener?.(updateDesktopMode);
  }, []);

  return isDesktop;
};
