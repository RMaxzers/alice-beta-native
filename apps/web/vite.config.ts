import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy the API to the local backend. The Origin header is dropped because the backend only
// accepts its own origin; the CSRF header is still required and checked.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        configure: (proxy) => proxy.on("proxyReq", (req) => req.removeHeader("origin")),
      },
    },
  },
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
});
