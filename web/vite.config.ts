import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // CERTIFLOW_API_PORT lets a second checkout (e.g. a git worktree) use its own API server.
  server: { proxy: { "/api": `http://localhost:${process.env.CERTIFLOW_API_PORT || 8000}` } },
  build: {
    outDir: "dist", sourcemap: false,
    // Libraries change rarely: keep them in their own files so browsers cache them across releases.
    rollupOptions: { output: { manualChunks: { react: ["react", "react-dom", "react-router-dom"], ui: ["@radix-ui/react-dialog", "@radix-ui/react-dropdown-menu", "@radix-ui/react-tooltip", "cmdk", "sonner"] } } },
  },
});
