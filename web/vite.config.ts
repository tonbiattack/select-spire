import { defineConfig } from "vite";

// GitHub Pages serves the project under /<repo>/, so the base must match.
export default defineConfig({
  base: "/select-spire/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});
