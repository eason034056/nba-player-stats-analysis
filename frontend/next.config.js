/**
 * next.config.js - Next.js 配置檔
 * 
 * 定義 Next.js 應用的各種設定
 * 包括：
 * - 環境變數
 * - API 代理
 * - 圖片優化設定
 * - 等等
 */

/** @type {import('next').NextConfig} */
const nextConfig = {
  // reactStrictMode: 啟用 React 嚴格模式
  // 有助於發現潛在問題（如副作用）
  reactStrictMode: true,
  
  // 環境變數
  // 這些變數會在建置時被替換
  // NEXT_PUBLIC_ 前綴的變數可以在瀏覽器端使用
  env: {
    // 後端 API 的 URL
    // 開發時指向本地，生產環境會被覆蓋
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },
  
  // 圖片優化設定
  images: {
    // 允許的外部圖片來源
    remotePatterns: [
      {
        protocol: "https",
        hostname: "a.espncdn.com",
        port: "",
        pathname: "/i/teamlogos/**",
      },
    ],
  },
  
  // 實驗性功能
  experimental: {
    // 啟用 Server Actions（用於伺服器端操作）
    // 這是 Next.js 13.4+ 的功能
  },
};

module.exports = nextConfig;

