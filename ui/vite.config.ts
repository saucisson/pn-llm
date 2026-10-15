import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API serves the built files under /ui; in development, Vite proxies the API.
export default defineConfig({
  base: "/ui/",
  plugins: [react()],
  server: { proxy: { "/v1": "http://localhost:8000" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
