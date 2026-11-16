import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // API aynı kökenden /api altında sunulur; oturum çerezi bu sayede yerelde de çalışır.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false, rewrite: (path) => path.replace(/^\/api/, "") } },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    clearMocks: true,
  },
});
