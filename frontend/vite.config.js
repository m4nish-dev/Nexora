import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 3000, strictPort: true },
  preview: { port: 3000, strictPort: true },
  // react-dom + framer-motion + the markdown stack form one ~175 kB gzip bundle; acceptable for a single-screen app.
  build: { chunkSizeWarningLimit: 700 },
});
