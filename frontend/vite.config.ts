import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://127.0.0.1:8766";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 5174,
    proxy: { "/api": backend, "/auth": backend, "/files": backend },
  },
});
