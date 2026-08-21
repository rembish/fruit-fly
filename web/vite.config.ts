import { defineConfig } from "vite";
import { resolve } from "node:path";

/**
 * Multi-page from the start: the hub and each cabinet get their own
 * entry, because they share nothing but the runtime and a visitor who
 * came for one game should not download the others.
 *
 * The root is the package directory rather than a `pages/` subtree, so
 * each HTML file's URL is its path — `/` for the hub, `/fff/` for the
 * first cabinet — and `src/` sits inside the root where the dev server
 * will serve it. A separate `pages/` directory reads more tidily and
 * costs a day: Vite normalises a `../src/...` script away to `/src/...`,
 * which 404s, and the symptom is a page that sits on its loading bar
 * with one failed request in the console and nothing else.
 *
 * `public/brain/` is served at `/brain/` — 17 MB of connectome, produced
 * by `python -m fruitfly export-web` and deliberately not in git.
 */
export default defineConfig({
  root: resolve(import.meta.dirname),
  publicDir: resolve(import.meta.dirname, "public"),
  build: {
    outDir: resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: { index: resolve(import.meta.dirname, "index.html") },
    },
  },
  worker: { format: "es" },
  server: { port: 5173, open: false },
  test: {
    // Colocated *.test.ts next to the modules they test, as the plan
    // says: a test that lives beside its subject gets read.
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
