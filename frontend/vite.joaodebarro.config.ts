import { defineConfig, type Plugin } from "vite"
import react from "@vitejs/plugin-react"
import { resolve } from "path"
import { readdirSync, readFileSync } from "fs"

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

// ORDEM 041: o service worker e o manifesto do app instalável vão junto no build (mesma pasta
// do HTML, para o service worker controlar o app inteiro).
const pwa: Plugin = {
  name: "jdb-pwa",
  generateBundle() {
    for (const f of ["sw-jdb.js", "manifest-jdb.webmanifest"]) {
      this.emitFile({ type: "asset", fileName: f, source: readFileSync(resolve(__dirname, f), "utf-8") })
    }
    // ORDEM 052 / D-103: logo e ícones do JdB Laudo (aprovados pelo Alan em 14/11/2026)
    for (const f of readdirSync(resolve(__dirname, "jdb-marca"))) {
      this.emitFile({ type: "asset", fileName: `jdb-marca/${f}`, source: readFileSync(resolve(__dirname, "jdb-marca", f)) })
    }
  },
}

export default defineConfig({
  plugins: [react(), indexHtml, pwa],
  base: "/assets-jdb/",
  publicDir: false,
  build: {
    outDir: "dist-joaodebarro",
    assetsDir: ".",
    emptyOutDir: true,
    target: "es2020",
    // ORDEM 053 (S1/S2): páginas públicas do próprio app (só local)
    rollupOptions: { input: { app: resolve(__dirname, "joaodebarro.html"), site: resolve(__dirname, "site.html"), planos: resolve(__dirname, "planos.html") } },
  },
  // ORDEM 046: JDB_PORTA / JDB_API permitem subir uma tela de TESTE ligada a um servidor de teste
  // (banco temporário), sem mexer no par real 5177 → 8866.
  server: {
    port: Number(process.env.JDB_PORTA || 5177),
    proxy: {
      "/api": `http://127.0.0.1:${process.env.JDB_API || 8866}`,
      "/ws": { target: `ws://127.0.0.1:${process.env.JDB_API || 8866}`, ws: true },
    },
  },
})
