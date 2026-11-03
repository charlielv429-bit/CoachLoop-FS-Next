import { defineConfig, loadEnv } from "vite";
export default defineConfig(({ mode }) => {
  // Only read backend routing variables; never expose the backend API key.
  const env = loadEnv(mode, "../backend", "BACKEND_");
  const target =
    env.BACKEND_URL || `http://127.0.0.1:${env.BACKEND_PORT || "8000"}`;
  return { server: { proxy: { "/api": target } } };
});
