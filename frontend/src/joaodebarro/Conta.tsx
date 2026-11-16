/* ORDEM 053 (L20): "Configurações" como lista. Cada linha abre uma tela que o app já tem:
 * Meus dados → Meu cadastro (042); Marca e modelos → logo, cores e modelos; Tabela de preços → a tabela (184);
 * Minhas regras (042); Avisos; Dados de pagamento (dados do contratado, 037); Meu plano (040, item 5
 * da 054); Coletor e sistema (a tela de configurações de antes); Avaliadores (só o Alan); Sair. */
import { useEffect, useState, type ReactNode } from 'react'
import { Banknote, BookOpen, ChevronRight, Cpu, LogOut, Palette, Tag, Trash2, UserRound, Users, Wallet } from 'lucide-react'
import { get } from './api'
import { DadosContratado } from './Propostas'
import { useStore, type Tela } from './store'
import { token } from './token'

function Linha({ icone, rotulo, onClick, soCelular = false }: { icone: ReactNode; rotulo: string; onClick: () => void; soCelular?: boolean }) {
  return (
    <li className={soCelular ? 'lg:hidden' : undefined}>
      <button type="button" className="linha-l20" onClick={onClick}>
        <span className="icone-l20" aria-hidden="true">{icone}</span>
        <span className="flex-1 text-left">{rotulo}</span>
        <ChevronRight size={22} aria-hidden="true" />
      </button>
    </li>
  )
}

export default function Conta() {
  const ir = useStore((s) => s.ir)
  const [eu, setEu] = useState('')
  useEffect(() => { get<{ id: string }>('/avaliadores/eu').then((r) => setEu(r.id)).catch(() => undefined) }, [])
  const vai = (t: Tela) => () => ir(t)
  return (
    <section className="tela-simples">
      <h1 className="titulo-jdb">Configurações</h1>
      <ul className="lista-l20">
        <Linha icone={<UserRound size={22} />} rotulo="Meus dados" onClick={vai('cadastro')} />
        <Linha icone={<Palette size={22} />} rotulo="Marca e modelos" onClick={vai('marca')} />
        <Linha icone={<Tag size={22} />} rotulo="Tabela de preços" onClick={vai('precos')} />
        <Linha icone={<Banknote size={22} />} rotulo="Dados de pagamento" onClick={vai('pagamento')} />
        <Linha icone={<BookOpen size={22} />} rotulo="Minhas regras" onClick={vai('regras')} />
        <Linha icone={<Cpu size={22} />} rotulo="Coletor e sistema" onClick={vai('sistema')} />
        <Linha icone={<Trash2 size={22} />} rotulo="Lixeira" onClick={vai('lixeira')} />
        {eu === 'AV-0001' && <Linha icone={<Users size={22} />} rotulo="Avaliadores" onClick={vai('avaliadores')} />}
        {/* 189: Avisos, Meu plano e Sair saíram (estão no menu); no celular, a "Conta" ganha Meu plano e Sair */}
        <Linha soCelular icone={<Wallet size={22} />} rotulo="Meu plano" onClick={vai('plano')} />
        <Linha soCelular icone={<LogOut size={22} />} rotulo="Sair" onClick={() => { token.limpar(); useStore.getState().sair() }} />
      </ul>
      {/* 172-4: a seção "Google" (169) saiu do caminho; o componente GoogleConta fica guardado em GoogleDocs.tsx */}
    </section>
  )
}

/** "Dados de pagamento": os dados do contratado que entram no contrato (CPF, endereço, e-mail, Pix). */
export function Pagamento() {
  const ir = useStore((s) => s.ir)
  return (
    <section className="tela-simples">
      <button type="button" className="voltar-jdb" onClick={() => ir('config')}>← Configurações</button>
      <h1 className="titulo-jdb">Dados de pagamento</h1>
      <p className="sub-jdb">Entram no seu contrato. Ficam só neste computador.</p>
      <DadosContratado aberto />
    </section>
  )
}
