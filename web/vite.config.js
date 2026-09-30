import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/PBHS_MEMO_CONVERTER/teacher-app/",
  plugins: [react()],
  build: {
    outDir: "../docs/teacher-app",
    emptyOutDir: true,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/testSetup.js",
    css: true,
  },
});
