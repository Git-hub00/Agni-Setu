import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Same-origin API in development: the browser talks to Vite, which proxies /api to the
// host-running Django server (docs/10_BUILD_GUIDE.md s.5). Production serves both behind Nginx.
export default defineConfig({
  plugins: [react(), tailwindcss()],
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
    sourcemap: true,
  },
});
