/**
 * tailwind.config.ts - Tailwind CSS 配置檔（極簡風版本）
 * 
 * 配色方案 (60-30-10 Rule):
 * - #FFF2DF (60%) - 暖米色背景
 * - #E92016 (30%) - 紅色強調
 * - #F9DC24 (10%) - 黃色點綴
 */

import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  
  theme: {
    extend: {
      // 極簡配色
      colors: {
        // 主色調：暖米色系
        cream: {
          DEFAULT: "#FFF2DF",
          light: "#FFFAF5",
          dark: "#F5E6D0",
        },
        // 強調色：紅色
        red: {
          DEFAULT: "#E92016",
          light: "#FF3B2F",
          dark: "#C41A12",
        },
        // 點綴色：黃色
        yellow: {
          DEFAULT: "#F9DC24",
          light: "#FFE94E",
          dark: "#E5C81A",
        },
        // 中性色
        dark: {
          DEFAULT: "#1A1A1A",
          light: "#2D2D2D",
        },
        gray: {
          DEFAULT: "#6B6B6B",
          light: "#A0A0A0",
        },
      },
      
      // 字體
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      
      // 動畫
      animation: {
        "fade-in": "fadeIn 0.2s ease-out forwards",
        "slide-up": "slideUp 0.25s ease-out",
      },
      
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      
      // 邊框半徑
      borderRadius: {
        "sm": "4px",
        "md": "8px",
        "lg": "12px",
        "xl": "16px",
      },
      
      // 邊框寬度
      borderWidth: {
        "DEFAULT": "2px",
        "1": "1px",
        "2": "2px",
        "3": "3px",
      },
    },
  },
  
  plugins: [],
};

export default config;
