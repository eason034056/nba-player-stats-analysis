/**
 * next.config.js - Next.js 配置檔
 *
 * dev 與 production build 使用不同的 distDir。
 * /api/backend/:path* 由 middleware.ts 轉到 BACKEND_API_URL。
 * 後端 origin 與 proxy secret 不放進 env:，避免被寫進 client bundle。
 */

const { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } = require("next/constants");
const { assertVercelHostingEnv } = require("./lib/proxy-request");

const getDistDir = (phase) =>
  phase === PHASE_DEVELOPMENT_SERVER ? ".next-dev" : ".next";

/** @type {import('next').NextConfig} */
const createNextConfig = (phase) => {
  // 只在 next build 檢查。Vercel 的 build 看得到這兩個變數。
  // 缺後端 origin、用了 http、或缺 proxy secret，都在這裡失敗。
  // next start 不在這裡擋：請求進到 middleware 時，Vercel 環境若仍沒有
  // secret，會回 500，不會把請求轉出去。
  if (phase === PHASE_PRODUCTION_BUILD) {
    assertVercelHostingEnv(process.env);
  }

  return {
    // 將 dev 與 build 的輸出分開，避免共用快取造成 chunk 對不上。
    distDir: getDistDir(phase),

    // reactStrictMode: 啟用 React 嚴格模式
    // 有助於發現潛在問題（如副作用）
    reactStrictMode: true,

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
      // 毫秒。middleware 的外部 rewrite 在 next dev / next start 走這個代理。
      // 未設定時 30 秒就中斷。Vercel 不讀這個值。
      proxyTimeout: 120_000,
    },
  };
};

module.exports = createNextConfig;
