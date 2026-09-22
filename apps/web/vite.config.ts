import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

/**
 * Dev server on :5173, API proxied to the FastAPI process on :8000.
 *
 * The proxy exists so the client uses same-origin `/api/...` paths in both modes. Without it
 * the built app would need a different base URL from the dev app, which is the kind of
 * difference that only shows up after deployment.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "jsdom" },
});
