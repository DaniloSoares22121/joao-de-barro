import { useState, type FormEvent } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { ApiError, login } from './api'
import { Marca } from './Marca'


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

  // ORDEM 053 (S4): "Entrar — Bom te ver de novo." Logo, e-mail, senha e o botão verde.
  return (
    <div className="login-s4">
      <form className="login-cx" onSubmit={enviar}>
        <Marca largura={170} />
        <div>
          <h1 className="titulo-jdb">Entrar</h1>
          <p className="sub-jdb">Bom te ver de novo.</p>
        </div>
        <label className="grid gap-1">
          <span className="rotulo-s4">E-mail</span>
          <input className="campo-grande" type="email" inputMode="email" autoComplete="username" autoCapitalize="none"
                 spellCheck={false} required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <div className="grid gap-1">
          <label className="rotulo-s4" htmlFor="login-senha">Senha</label>
          <div className="relative">
            <input id="login-senha" className={`campo-grande pr-14 ${erro ? 'campo-erro' : ''}`} type={verSenha ? 'text' : 'password'}
                   autoComplete="current-password" required value={senha} onChange={(e) => setSenha(e.target.value)} />
            <button type="button" onClick={() => setVerSenha((v) => !v)}
                    aria-label={verSenha ? 'Ocultar a senha' : 'Mostrar a senha'} aria-pressed={verSenha}
                    className="foco absolute inset-y-0 right-0 flex w-14 items-center justify-center text-[var(--chumbo)]">
              {verSenha ? <EyeOff size={22} aria-hidden="true" /> : <Eye size={22} aria-hidden="true" />}
            </button>
          </div>
          {erro && <p className="erro-s4" role="alert">{erro}</p>}
        </div>
        <button className="btn-verde w-full" type="submit" disabled={enviando}>{enviando ? 'Entrando…' : 'Entrar'}</button>
      </form>
    </div>
  )
}
