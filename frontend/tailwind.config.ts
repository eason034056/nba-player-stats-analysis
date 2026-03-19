import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  
  theme: {
    extend: {
      colors: {
        cream: {
          DEFAULT: "#F6EFE2",
          light: "#FFFAF2",
          dark: "#D6CAB7",
        },
        red: {
          DEFAULT: "#FF886C",
          light: "#FFD0C1",
          dark: "#DF6B52",
        },
        yellow: {
          DEFAULT: "#F3C775",
          light: "#FAE3AB",
          dark: "#E0B55D",
        },
        dark: {
          DEFAULT: "#08101D",
          light: "#15233A",
        },
        gray: {
          DEFAULT: "#95A6C5",
          light: "#CAD4E6",
        },
      },

      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "serif"],
        mono: ["JetBrains Mono", "monospace"],
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
        md: "16px",
        lg: "24px",
        xl: "32px",
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
      },
    },
  },
  
  plugins: [],
};

export default config;
