import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// En desarrollo, /api se reenvía al backend FastAPI (uvicorn en el puerto 8000, o API_URL si se define).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8000" } },
  // Librerías en archivos aparte: cambian poco, así el navegador las reutiliza entre versiones de la app.
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          graficos: ["recharts"],
          mapa: ["leaflet", "react-leaflet"],
        },
      },
    },
  },
});
