import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { demoApi } from "./demo/mock";

// Isolated demo for design capture and visual QA: `npm run demo` → http://127.0.0.1:5174 with synthetic
// fixtures (demo/mock.ts). No backend, no real data. Login: any user, password "demo".
export default defineConfig({
  plugins: [react(), demoApi()],
  server: { host: "127.0.0.1", port: 5174, strictPort: true },
});
