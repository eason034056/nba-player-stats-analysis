import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
  ],
  
  theme: {
    extend: {
      colors: {
        canvas: "#EEEEEE",
        ink: "#1D1530",
        muted: "#625B70",
        line: "#DEDAE5",
        brand: {
          DEFAULT: "#3E0F8D",
          deep: "#2F0A6E",
          soft: "#9564DD",
          tint: "#ECE6F7",
          mist: "#E6DDF6",
          ink: "#2A0A60",
        },
        accent: {
          DEFAULT: "#E4DA72",
          ink: "#2A0A60",
        },
        cream: {
          DEFAULT: "#F6EFE2",
          light: "#FFFAF2",
          dark: "#D6CAB7",
        },
        red: {
          DEFAULT: "#8E2C50",
          light: "#F6E3EA",
          dark: "#6E1E34",
        },
        yellow: {
          DEFAULT: "#E4DA72",
          light: "#F6F2D2",
          dark: "#5A5310",
        },
        dark: {
          DEFAULT: "#1D1530",
          light: "#4A4458",
        },
        gray: {
          DEFAULT: "#625B70",
          // Light ink for text that sits on a dark code block.
          light: "#D9CEF0",
        },
        // Names follow the No-Vig token list. `neutral` is not used:
        // Tailwind already owns that scale, so the chevron gray is tone-neutral.
        surface: "#FFFFFF",
        "ink-2": "#4A4458",
        faint: "#8A8496",
        eyebrow: "#7B4FC4",
        against: "#B4436C",
        "under-text": "#5B3A99",
        "line-strong": "#D3CCDF",
        divider: "#EEEBF2",
        seg: "#F3F1F6",
        panel: "#F7F6F9",
        grid: "#F1EEF4",
        "list-gap": "#E6E2EC",
        "under-bar": "#C9B4EE",
        "chart-line": "#B3A63A",
        lean: "#E3DAF3",
        pass: "#E2E2E2",
        "tone-neutral": "#B9B3C4",
        "agent-border": "#E3DFE9",
        "tag-against": "#F6E3EA",
        "tag-against-ink": "#8E2C50",
        "tag-neutral": "#F1F0F3",
        "card-footer": "#BFAEE3",
      },

      fontFamily: {
        sans: ["var(--font-sans)", "Instrument Sans", "system-ui", "sans-serif"],
        display: ["var(--font-sans)", "Instrument Sans", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "ui-monospace", "monospace"],
      },

      animation: {
        "fade-in": "fadeIn 0.35s ease-out forwards",
        "slide-up": "slideUp 0.4s cubic-bezier(0.22, 1, 0.36, 1)",
        "soft-pulse": "softPulse 4s ease-in-out infinite",
      },

      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(18px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        softPulse: {
          "0%, 100%": { opacity: "0.85", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.02)" },
        },
      },

      borderRadius: {
        sm: "10px",
        md: "14px",
        lg: "20px",
        xl: "24px",
        "2xl": "28px",
        badge: "6px",
        "mark-sm": "9px",
        mark: "10px",
        control: "12px",
        tile: "16px",
        row: "18px",
        card: "20px",
        game: "22px",
        sheet: "24px",
        hero: "28px",
      },

      fontSize: {
        hero: ["clamp(34px, 6cqi, 60px)", { lineHeight: "1", letterSpacing: "-0.035em" }],
        "hero-mobile": ["30px", { lineHeight: "1.05", letterSpacing: "-0.03em" }],
        "page-title": ["clamp(32px, 5cqi, 52px)", { lineHeight: "1", letterSpacing: "-0.035em" }],
        "event-title": ["clamp(24px, 3.6cqi, 36px)", { lineHeight: "1.05", letterSpacing: "-0.03em" }],
        "read-title": ["clamp(30px, 5cqi, 48px)", { lineHeight: "1.05", letterSpacing: "-0.035em" }],
        eyebrow: ["12px", { lineHeight: "1.2", letterSpacing: "0.12em" }],
        "eyebrow-mobile": ["11px", { lineHeight: "1.2", letterSpacing: "0.12em" }],
        prob: ["30px", { lineHeight: "1" }],
      },

      maxWidth: {
        page: "1200px",
      },

      height: {
        header: "68px",
      },

      borderWidth: {
        DEFAULT: "1px",
        "1": "1px",
        "2": "1px",
        "3": "1px",
      },

      boxShadow: {
        glow: "0 24px 70px rgba(2, 8, 20, 0.35)",
        panel: "0 28px 90px rgba(2, 8, 20, 0.4)",
        // The only shadow in the redesign. Cards use a 1px border.
        drawer: "-20px 0 60px rgba(29, 21, 48, 0.18)",
      },
    },
  },
  
  plugins: [],
};

export default config;
