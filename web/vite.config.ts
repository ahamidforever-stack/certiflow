import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // CERTIFLOW_API_PORT lets a second checkout (e.g. a git worktree) use its own API server.
  server: { proxy: { "/api": `http://localhost:${process.env.CERTIFLOW_API_PORT || 8000}` } },
  build: { outDir: "dist", sourcemap: false },
});
