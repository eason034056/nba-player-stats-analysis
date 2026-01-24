/**
 * tailwind.config.ts - Tailwind CSS 配置檔
 * 
 * Tailwind CSS 是一個 utility-first 的 CSS 框架
 * 這個檔案定義了專案的設計系統（顏色、字體、間距等）
 */

import type { Config } from "tailwindcss";

const config: Config = {
  // content: 告訴 Tailwind 要掃描哪些檔案來找出使用的 class
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  
  theme: {
    extend: {
      // 自定義顏色
      colors: {
        // 主色調：深藍色系（NBA 風格）
        primary: {
          50: "#eff6ff",
          100: "#dbeafe",
          200: "#bfdbfe",
          300: "#93c5fd",
          400: "#60a5fa",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          800: "#1e40af",
          900: "#1e3a8a",
          950: "#172554",
        },
        // 強調色：琥珀/橙色（用於重要資訊和品牌色）
        accent: {
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
          950: "#451a03",
        },
        // 成功色：翡翠綠（用於有利賠率）
        success: {
          400: "#34d399",
          500: "#22c55e",
          600: "#16a34a",
        },
        // 警告色：紅色（用於不利賠率）
        danger: {
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
        },
      },
      
      // 自定義字體
      fontFamily: {
        // 使用 Space Grotesk 作為主要字體（獨特的幾何風格）
        sans: ["Space Grotesk", "system-ui", "sans-serif"],
        // 使用等寬字體顯示數字
        mono: ["JetBrains Mono", "monospace"],
      },
      
      // 自定義動畫
      animation: {
        // 淡入動畫
        "fade-in": "fadeIn 0.3s cubic-bezier(0.22, 1, 0.36, 1) forwards",
        // 滑入動畫
        "slide-up": "slideUp 0.4s cubic-bezier(0.22, 1, 0.36, 1)",
        // 脈動動畫
        "pulse-subtle": "pulseSubtle 2s ease-in-out infinite",
        // 發光脈動
        "pulse-glow": "pulseGlow 2s ease-in-out infinite",
      },
      
      // 定義 keyframes
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseSubtle: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.7" },
        },
        pulseGlow: {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
      },
      
      // 背景圖片
      backgroundImage: {
        "gradient-radial": "radial-gradient(var(--tw-gradient-stops))",
        "gradient-conic": "conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))",
      },
      
      // 自定義陰影
      boxShadow: {
        "glow-blue": "0 0 30px rgba(59, 130, 246, 0.15)",
        "glow-amber": "0 0 30px rgba(245, 158, 11, 0.15)",
      },
    },
  },
  
  // 插件
  plugins: [],
};

export default config;

