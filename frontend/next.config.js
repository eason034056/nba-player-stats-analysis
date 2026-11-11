/**
 * next.config.js - Next.js 配置檔
 *
 * dev 與 production build 使用不同的 distDir。
 * 瀏覽器打同源的 /api/backend/:path*，rewrite 轉到 BACKEND_API_URL。
 * 後端 origin 不放進 env:，避免被寫進 client bundle。
 */

const { PHASE_DEVELOPMENT_SERVER } = require("next/constants");
const { buildBackendRewrite } = require("./lib/backend-origin");

const getDistDir = (phase) =>
  phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next";

/** @type {import('next').NextConfig} */
const createNextConfig = (phase) => ({
  // 將 dev 與 build 的輸出分開，避免共用快取造成 chunk 對不上。
  distDir: getDistDir(phase),

  // reactStrictMode: 啟用 React 嚴格模式
  // 有助於發現潛在問題（如副作用）
  reactStrictMode: true,

  async rewrites() {
    // :path* 是 /api/backend/ 後面的整段，含 /api/nba 與 /api/wnba。
    // 查詢字串由 Next.js 轉送，不必寫進 destination。
    return [buildBackendRewrite(process.env)];
  },

  // 圖片優化設定
  images: {
    // 允許的外部圖片來源。球隊 logo 來自 ESPN，不是後端 origin。
    remotePatterns: [
      {
        protocol: "https",
        hostname: "a.espncdn.com",
        port: "",
        pathname: "/i/teamlogos/**",
      },
    ],
  },

  experimental: {
    // 毫秒。未設定時，next dev / next start 的 rewrite 代理 30 秒就中斷。
    // Vercel 不讀這個值，平台對外部 rewrite 的上限是 120 秒。
    proxyTimeout: 120_000,
  },
});

module.exports = createNextConfig;
