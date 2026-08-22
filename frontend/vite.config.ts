import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
  },
  build: {
    rollupOptions: {
      // the trusted-circle companion page is a second entry point, not a
      // route inside the main dashboard SPA -- it's meant to be opened by
      // someone who isn't Amara, on their own device
      input: {
        main: resolve(__dirname, "index.html"),
        companion: resolve(__dirname, "companion.html"),
      },
    },
  },
});
