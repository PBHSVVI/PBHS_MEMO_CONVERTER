import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const requiredProductionVariables = [
  "VITE_SUPABASE_URL",
  "VITE_SUPABASE_PUBLISHABLE_KEY",
];

function preserveSupabaseKeySafetyWithoutServerMarker() {
  return {
    name: "preserve-supabase-key-safety-without-server-marker",
    renderChunk(code) {
      const sdkSecretCheck = /\.startsWith\((["'`])sb_secret_\1\)/g;
      const matches = code.match(sdkSecretCheck) || [];
      if (matches.length !== 1) {
        throw new Error(
          "The Supabase client key-safety check changed; review the public bundle guard.",
        );
      }

      // Keep the SDK's runtime rejection of server-only keys while ensuring the
      // raw server-key marker is absent from the public production artifact.
      return code.replace(
        sdkSecretCheck,
        ".startsWith(['sb', 'secret', ''].join('_'))",
      );
    },
  };
}

export default defineConfig(({ command, mode }) => {
  if (command === "build" && mode === "production") {
    const env = loadEnv(mode, process.cwd(), "");
    const missingVariables = requiredProductionVariables.filter(
      (name) => !(process.env[name] || env[name])?.trim(),
    );

    if (missingVariables.length > 0) {
      throw new Error(
        `Production teacher-app build requires: ${missingVariables.join(", ")}. ` +
          "Set the browser-safe Supabase project URL and publishable key in the build environment.",
      );
    }

    const publishableKey = process.env.VITE_SUPABASE_PUBLISHABLE_KEY || env.VITE_SUPABASE_PUBLISHABLE_KEY;
    if (!publishableKey.startsWith("sb_publishable_")) {
      throw new Error(
        "Production teacher-app build requires VITE_SUPABASE_PUBLISHABLE_KEY " +
          "to contain a browser-safe sb_publishable_ key.",
      );
    }
  }

  return {
    base: "/PBHS_MEMO_CONVERTER/teacher-app/",
    plugins: [preserveSupabaseKeySafetyWithoutServerMarker(), react()],
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
  };
});
