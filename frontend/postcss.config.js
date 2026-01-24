/**
 * postcss.config.js - PostCSS 配置
 * 
 * PostCSS 是一個用 JavaScript 轉換 CSS 的工具
 * 這裡用於：
 * 1. tailwindcss: 處理 Tailwind CSS 指令
 * 2. autoprefixer: 自動加入瀏覽器前綴
 */

module.exports = {
  plugins: {
    // Tailwind CSS 插件
    // 處理 @tailwind 指令和工具類別
    tailwindcss: {},
    
    // Autoprefixer 插件
    // 自動加入 -webkit-、-moz- 等瀏覽器前綴
    autoprefixer: {},
  },
};

