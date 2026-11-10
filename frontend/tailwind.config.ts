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
