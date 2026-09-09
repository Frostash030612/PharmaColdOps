import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

/* base:"./" — every built asset resolves relative to the page, so dist/ can be
   served from any static host (python -m http.server, a sub-path, or later a
   FastAPI StaticFiles mount beside src/api) without a rebuild. */
export default defineConfig({
  plugins: [vue()],
  base: "./",
});
