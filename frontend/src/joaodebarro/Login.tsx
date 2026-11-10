import { useState, type FormEvent } from 'react'
import { Eye, EyeOff, FileCheck2, FolderUp, Search } from 'lucide-react'
import { ApiError, login } from './api'
import { Marca } from './Marca'

const PASSOS = [
  { icone: FolderUp, titulo: 'Você envia', texto: 'Documentos do imóvel e fotos da vistoria.' },
  { icone: Search, titulo: 'O João de Barro pesquisa', texto: 'Referenciais de mercado, seleção e cálculo do valor.' },
  { icone: FileCheck2, titulo: 'Você revisa e assina', texto: 'Laudo em Word e PDF, com a planilha de cálculo.' },
] as const

export default function Login() {
  const [email, setEmail] = useState('')
  const [senha, setSenha] = useState('')
  const [verSenha, setVerSenha] = useState(false)
  const [erro, setErro] = useState('')
  const [enviando, setEnviando] = useState(false)

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setErro('')
    setEnviando(true)
    try {
      await login(email.trim(), senha)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setErro('E-mail ou senha incorretos.')
      else if (err instanceof ApiError && err.status === 429) setErro('Muitas tentativas. Aguarde alguns minutos.')
      else setErro('Não foi possível entrar. Verifique a conexão e tente novamente.')
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="entra grid w-full max-w-3xl overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm md:grid-cols-[1fr_1.05fr]">
        <aside className="hidden flex-col justify-between gap-8 bg-barro-claro p-8 md:flex">
          <Marca grande />
          <ol className="space-y-5">
            {PASSOS.map(({ icone: Icone, titulo, texto }) => (
              <li key={titulo} className="flex gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-barro ring-1 ring-inset ring-orange-200">
                  <Icone size={18} aria-hidden="true" />
                </span>
                <span>
                  <span className="block text-sm font-semibold text-stone-900">{titulo}</span>
                  <span className="block text-sm text-stone-600">{texto}</span>
                </span>
              </li>
            ))}
          </ol>
          <p className="text-xs text-stone-500">Acesso exclusivo do avaliador.</p>
        </aside>

        <form className="space-y-4 p-6 sm:p-8" onSubmit={enviar}>
          <div className="md:hidden"><Marca grande /></div>
          <div>
            <h1 className="text-xl font-semibold text-stone-900">Entrar</h1>
            <p className="mt-1 text-sm text-stone-500">Use o e-mail e a senha da sua conta.</p>
          </div>
          <label className="block">
            <span className="rotulo">E-mail</span>
            <input className="input" type="email" inputMode="email" autoComplete="username" autoCapitalize="none"
                   spellCheck={false} required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <div>
            <label className="rotulo" htmlFor="login-senha">Senha</label>
            <div className="relative">
              <input id="login-senha" className="input pr-11" type={verSenha ? 'text' : 'password'}
                     autoComplete="current-password" required value={senha} onChange={(e) => setSenha(e.target.value)} />
              <button type="button" onClick={() => setVerSenha((v) => !v)}
                      aria-label={verSenha ? 'Ocultar a senha' : 'Mostrar a senha'} aria-pressed={verSenha}
                      className="foco absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-stone-400 hover:text-stone-700">
                {verSenha ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
              </button>
            </div>
          </div>
          {erro && <p className="faixa-erro" role="alert">{erro}</p>}
          <button className="btn w-full" type="submit" disabled={enviando}>{enviando ? 'Entrando…' : 'Entrar'}</button>
        </form>
      </div>
    </div>
  )
}
