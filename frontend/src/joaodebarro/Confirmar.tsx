/* Janela de confirmação própria (no lugar de window.confirm): título, texto e dois botões. */
import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'

export default function Confirmar({ titulo, texto, rotuloConfirmar, perigo = false, ocupado = false, erro, aoConfirmar, aoCancelar }: {
  titulo: string
  texto: string
  rotuloConfirmar: string
  /** Botão de confirmar em vermelho (ação destrutiva). */
  perigo?: boolean
  ocupado?: boolean
  erro?: string
  aoConfirmar: () => void
  aoCancelar: () => void
}) {
  const id = useId()
  const cancelar = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    cancelar.current?.focus()
    const tecla = (e: KeyboardEvent) => { if (e.key === 'Escape' && !ocupado) aoCancelar() }
    document.addEventListener('keydown', tecla)
    return () => document.removeEventListener('keydown', tecla)
  }, [aoCancelar, ocupado])

  // ORDEM 060: desenhada no <body>: dentro da tela (que tem animação) ela ficava por baixo do menu do celular
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 p-4 sm:items-center"
         onMouseDown={(e) => { if (e.target === e.currentTarget && !ocupado) aoCancelar() }}>
      <div role="alertdialog" aria-modal="true" aria-labelledby={`${id}-t`} aria-describedby={`${id}-d`}
           className="cartao-pad w-full max-w-md space-y-3 shadow-xl">
        <h2 id={`${id}-t`} className="titulo-sec">{titulo}</h2>
        <p id={`${id}-d`} className="text-sm text-stone-600">{texto}</p>
        {erro && <p className="erro-txt" role="alert">{erro}</p>}
        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
          <button ref={cancelar} type="button" className="btn-sec" onClick={aoCancelar} disabled={ocupado}>Cancelar</button>
          <button type="button" disabled={ocupado} onClick={aoConfirmar}
                  className={perigo ? 'btn-perigo' : 'btn'}>
            {ocupado ? 'Aguarde…' : rotuloConfirmar}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
