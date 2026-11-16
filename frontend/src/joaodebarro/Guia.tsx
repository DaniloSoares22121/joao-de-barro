/* ORDEM 053 / 057 (L16): "O que você quer fazer? Eu te guio passo a passo." Três modalidades com o
 * que a base de conhecimento diz delas (K0.2: uso; K3: sem CNAI o sistema só emite OV). "Fazer junto"
 * leva à caixa da L2 já com a modalidade escrita. Sem prazo: a base não tem um tempo para cada uma. */
import { useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { comecarCom } from './NovoSimples'
import { useStore } from './store'

const MODS = [
  { id: 'OV', nome: 'Opinião de Valor', curta: 'Não precisa de CNAI.', serve: 'negociação entre particulares — dizer quanto vale o imóvel hoje.',
    precisa: 'documentos do imóvel (matrícula ou escritura, IPTU) e fotos da vistoria.' },
  { id: 'AM', nome: 'PTAM não judicial', curta: 'Precisa de CNAI.', serve: 'venda, locação e decisão de empresa.',
    precisa: 'documentos do imóvel (matrícula ou escritura, IPTU), fotos da vistoria e o seu CNAI no cadastro.' },
  { id: 'AMJ', nome: 'PTAM judicial', curta: 'Para processo.', serve: 'processo: divórcio, partilha, inventário, perícia.',
    precisa: 'documentos do imóvel, fotos da vistoria, os dados do processo e os quesitos, e o seu CNAI no cadastro.' },
] as const

export default function Guia() {
  const ir = useStore((s) => s.ir)
  const [m, setM] = useState<(typeof MODS)[number]>(MODS[0])
  return (
    <section className="tela-simples tela-larga">
      <button type="button" className="voltar-jdb" onClick={() => ir('novo')}><ArrowLeft size={18} aria-hidden="true" /> Novo trabalho</button>
      <div>
        <h1 className="titulo-jdb">O que você quer fazer?</h1>
        <p className="sub-jdb">Eu te guio passo a passo.</p>
      </div>
      <div className="mods-l16" role="radiogroup" aria-label="Modalidade">
        {MODS.map((x) => (
          <button key={x.id} type="button" role="radio" aria-checked={m.id === x.id} onClick={() => setM(x)}>
            <b>{x.nome}</b><span>{x.curta}</span>
          </button>
        ))}
      </div>
      <div className="proximo-passo">
        <h2 className="titulo-cartao">{m.nome}</h2>
        <p className="texto"><b>Para que serve:</b> {m.serve}</p>
        <p className="texto"><b>Você vai precisar:</b> {m.precisa}</p>
        <div className="botoes"><button type="button" className="btn-verde" onClick={() => { comecarCom(`Quero fazer ${m.nome === 'Opinião de Valor' ? 'uma' : 'um'} ${m.nome}.`); ir('novo') }}>Fazer junto</button></div>
      </div>
    </section>
  )
}
