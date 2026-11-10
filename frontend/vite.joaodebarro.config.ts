import { defineConfig, type Plugin } from "vite"
import react from "@vitejs/plugin-react"
import { resolve } from "path"

// Build do João de Barro (joaodebarro.brixly.com.br) — UI do avaliador.
// Sai em dist-joaodebarro/, servido por backend/lovable/main.py (_joaodebarro_host).
// base /assets-jdb/: o painel principal já monta "/assets" com os arquivos dele.
// O HTML de entrada é joaodebarro.html, mas o backend espera dist-joaodebarro/index.html.
const indexHtml: Plugin = {
  name: "jdb-index-html",
  enforce: "post",
  generateBundle(_o, bundle) {
    const f = bundle["joaodebarro.html"]
    if (f) {
      f.fileName = "index.html"
    }
  },
}

export default defineConfig({
  plugins: [react(), indexHtml],
  base: "/assets-jdb/",
  publicDir: false,
  build: {
    outDir: "dist-joaodebarro",
    assetsDir: ".",
    emptyOutDir: true,
    target: "es2020",
    rollupOptions: { input: resolve(__dirname, "joaodebarro.html") },
  },
  server: {
    port: 5177,
    proxy: { "/api": "http://127.0.0.1:8866", "/ws": { target: "ws://127.0.0.1:8866", ws: true } },
  },
})
