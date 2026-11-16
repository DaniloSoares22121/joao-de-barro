import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { JanelaEditor } from './EditorLaudo'
// ORDEM 052 / D-103: fontes do JdB servidas junto com o app (funcionam sem internet)
import '@fontsource/sora/700.css'
import '@fontsource/manrope/400.css'
import '@fontsource/manrope/700.css'
import './estilo.css'
import { registrar } from './avisos'

// ORDEM 049: o service worker é registrado ao abrir o app (instalar como app e receber o Compartilhar)
void registrar()

// ORDEM 141: "?editor=<trabalho>" é a JANELA SEPARADA do laudo editável (só o editor, sem o resto do app)
const trabalhoDoEditor = new URLSearchParams(window.location.search).get('editor')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {trabalhoDoEditor ? <JanelaEditor jobId={trabalhoDoEditor} /> : <App />}
  </React.StrictMode>,
)
