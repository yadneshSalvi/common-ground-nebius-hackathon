import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  root: "web",
  publicDir: "../public",
  build: { outDir: "../dist/broker", emptyOutDir: true },
  server: { host: "127.0.0.1", port: 4301, strictPort: true },
  preview: { host: "127.0.0.1", port: 4301, strictPort: true },
});
