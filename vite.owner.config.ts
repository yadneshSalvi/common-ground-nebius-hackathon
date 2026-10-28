import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  root: "owner-web",
  publicDir: "../public",
  build: { outDir: "../dist/owner", emptyOutDir: true },
});
