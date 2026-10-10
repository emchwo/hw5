import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Board runs on http://localhost:5173 and calls the FastAPI backend at http://localhost:8000.
export default defineConfig({
  plugins: [react()],
  server: { port: Number(process.env.PORT ?? 5173), strictPort: true },
});
