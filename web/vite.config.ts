import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Same-origin API in development: the browser talks to Vite, which proxies /api to the
// host-running Django server (docs/10_BUILD_GUIDE.md s.5). Production serves both behind Nginx.
//
// Service worker (B11, docs/09 s.3): the worker precaches the static application shell only.
// It never caches /api responses or any authenticated data - offline case data lives in
// IndexedDB under the application's control (src/offline). A new worker waits until the user
// accepts the "reload" prompt in the shell, so unsent work is never interrupted mid-capture.
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "prompt",
      injectRegister: false,
      includeAssets: [],
      manifest: {
        name: "Agni Setu",
        short_name: "Agni Setu",
        description: "Fire-safety certificate case management",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#faf7f2",
        theme_color: "#8b1e1e",
        icons: [],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,woff2}"],
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/static\//, /^\/media\//],
        runtimeCaching: [],
        cleanupOutdatedCaches: true,
        clientsClaim: false,
        skipWaiting: false,
      },
      devOptions: {
        enabled: false,
      },
    }),
  ],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    // Maps are produced for internal symbolication (kept with the build artefacts) but the bundles
    // carry no sourceMappingURL and nginx answers 404 for *.map, so the implementation structure
    // is not published (security s.9 "information exposure"; G-07).
    sourcemap: "hidden",
  },
});
