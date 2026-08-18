/**
 * Build config for the render tests.
 *
 * The project has no test runner, and a P0 fix is the wrong moment to add one.
 * This bundles a test entry for Node with the toolchain already present (vite
 * + rolldown), leaving react/react-dom external so they resolve from
 * node_modules at run time. `renderToStaticMarkup` needs no DOM, so a render
 * that throws — which is precisely how the outage manifested — fails the run.
 */
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    ssr: true,
    outDir: "tests/.build",
    emptyOutDir: true,
    minify: false,
    target: "node20",
    rollupOptions: {
      input: [
        "tests/render-insights.tsx",
        "tests/render-error-boundary.tsx",
        "tests/render-live-monitor.tsx",
        // Not part of `make check`: this one renders against the live backend.
        "tests/live-smoke.tsx",
        "tests/verify-production.tsx",
      ],
      output: { entryFileNames: "[name].mjs", format: "es" },
    },
  },
});
