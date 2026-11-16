/* ORDEM 178 (com a 179 e a 180): a tela final do trabalho — depois do [Baixar para a revisão humana] e sempre que o
 * trabalho concluído é aberto. É a última tela do laudo: o João comemora (as peças do designer, D-150: ele voa uma vez
 * sobre o ninho e pousa; quem pede menos movimento vê o João parado), o título, o aviso de que a IA pode errar, o que
 * conferir primeiro e a Entrega. A assinatura saiu do sistema: o avaliador assina o PDF por fora. */
import { useRef } from 'react'
import { CaixaEntrega } from './Downloads'
import type { Job } from './tipos'

const MARCA = `${import.meta.env.BASE_URL}jdb-marca/`

const CSS = `
.jdb-final { display: grid; gap: 18px; }
.jdb-final-palco { position: relative; height: 190px; display: grid; place-items: center; overflow: hidden;
  background: radial-gradient(ellipse at 50% 85%, rgba(245,184,0,.22), rgba(245,184,0,0) 62%); border-radius: 16px; }
.jdb-final-ninho { width: 150px; height: 150px; }
.jdb-final-voo { position: absolute; width: 74px; height: 74px; left: calc(50% - 37px); top: 40px; opacity: 0;
  animation: jdbFinalVoo 2.6s ease-in-out 0.25s 1 both; }
.jdb-final-pousado { opacity: 0; animation: jdbFinalPousa 0.35s ease-out 2.75s 1 forwards; }
.jdb-final-vazio { animation: jdbFinalSai 0.3s ease-in 2.75s 1 forwards; }
.jdb-final-ponto { position: absolute; width: 9px; height: 9px; border-radius: 50%; opacity: 0;
  animation: jdbFinalPonto 1.1s ease-out 2.8s 1 both; }
@keyframes jdbFinalVoo {
  0% { opacity: 1; transform: translate(-150px, 70px) scale(.8) rotate(-8deg); }
  35% { opacity: 1; transform: translate(-40px, -30px) scale(1) rotate(4deg); }
  65% { opacity: 1; transform: translate(70px, -40px) scale(1) rotate(-4deg); }
  92% { opacity: 1; transform: translate(0, 18px) scale(.9) rotate(0); }
  100% { opacity: 0; transform: translate(0, 24px) scale(.85); } }
@keyframes jdbFinalPousa { to { opacity: 1; } }
@keyframes jdbFinalSai { to { opacity: 0; } }
@keyframes jdbFinalPonto { 0% { opacity: 0; transform: translate(0, 0) scale(.4); }
  25% { opacity: 1; } 100% { opacity: 0; transform: translate(var(--dx), var(--dy)) scale(1); } }
.jdb-final-titulo { font-family: "Sora", "Manrope", system-ui, sans-serif; font-weight: 700; color: var(--navy, #18283B);
  font-size: 24px; line-height: 1.25; margin: 0; text-align: center; }
.jdb-final-sub { margin: 0; text-align: center; color: #5B6470; font-size: 16px; }
.jdb-final-aviso { background: #FFF4CC; border: 2px solid #F5B800; border-left-width: 8px; border-radius: 12px;
  padding: 14px 16px; color: #18283B; font-size: 16px; line-height: 1.45; margin: 0; }
.jdb-final-conferir { margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }
.jdb-final-conferir li { display: flex; gap: 10px; align-items: flex-start; font-size: 16px; color: #18283B; }
.jdb-final-n { flex: 0 0 28px; height: 28px; border-radius: 50%; background: #18283B; color: #fff; display: grid;
  place-items: center; font-weight: 700; font-size: 14px; }
@media (max-width: 640px) { .jdb-final-titulo { font-size: 20px; } .jdb-final-palco { height: 160px; } }
@media (prefers-reduced-motion: reduce) {
  .jdb-final-voo, .jdb-final-ponto { display: none; }
  .jdb-final-pousado { opacity: 1; animation: none; }
  .jdb-final-vazio { display: none; }
}`

const PONTOS = [['-90px', '-60px', '#F5B800'], ['80px', '-70px', '#A0522D'], ['-60px', '-95px', '#18283B'],
  ['110px', '-30px', '#F5B800'], ['-120px', '-20px', '#A0522D'], ['30px', '-100px', '#F5B800']]

export default function TelaFinal({ job, temPontos, verPontos, fotosNovas = 0, verFotos }: {
  job: Job; temPontos: boolean; verPontos: () => void; fotosNovas?: number; verFotos?: () => void
}) {
  const d = job.dados
  const linha = [`Laudo nº ${job.numero}`, [d.tipo, d.bairro].filter(Boolean).join(' – ')].filter(Boolean).join(' · ')
  const palco = useRef<HTMLDivElement>(null)
  return (
    <section className="cartao-pad jdb-final" aria-labelledby="jdb-final-titulo"
             style={{ border: '2px solid #18283B', borderRadius: 16 }}>
      <style>{CSS}</style>
      <div className="jdb-final-palco" ref={palco} aria-hidden="true">
        <img className="jdb-final-ninho jdb-final-vazio" src={`${MARCA}ninho-vazio-claro.svg`} alt="" style={{ position: 'absolute' }} />
        <img className="jdb-final-ninho jdb-final-pousado" src={`${MARCA}jdb-parado-claro.svg`} alt="" />
        <img className="jdb-final-voo" src={`${MARCA}joao-voando-claro.svg`} alt="" />
        {PONTOS.map(([dx, dy, cor], i) => (
          <span key={i} className="jdb-final-ponto" style={{ left: 'calc(50% - 4px)', top: '50%', background: cor,
            ['--dx' as string]: dx, ['--dy' as string]: dy, animationDelay: `${2.8 + i * 0.05}s` }} />))}
      </div>
      <div className="grid gap-1">
        <h1 id="jdb-final-titulo" className="jdb-final-titulo">Seu laudo está pronto para revisar antes de assinar e enviar ao seu cliente</h1>
        <p className="jdb-final-sub">{linha}</p>
      </div>
      <p className="jdb-final-aviso" role="note">
        Este laudo foi feito com a ajuda de inteligência artificial, e a IA pode errar. Leia o laudo inteiro e confira números,
        áreas, referenciais, fotos e dados do cliente. A assinatura e a responsabilidade técnica são suas.
      </p>
      <div className="grid gap-2">
        <h2 className="titulo-sec" style={{ margin: 0 }}>O que conferir primeiro</h2>
        <ol className="jdb-final-conferir">
          <li><span className="jdb-final-n">1</span>
            <span>{temPontos ? 'Os pontos que o sistema marcou: copie a frase e ache no Word com Ctrl+F.' : 'O sistema não marcou nenhum ponto; mesmo assim, leia o laudo inteiro.'}
              {temPontos && <> <button type="button" className="btn-sec btn-peq" style={{ marginLeft: 6 }} onClick={verPontos}>Ver os pontos</button></>}</span></li>
          <li><span className="jdb-final-n">2</span><span>O valor final e a conta (na planilha).</span></li>
          <li><span className="jdb-final-n">3</span><span>O mapa da localização e a foto da fachada.</span></li>
        </ol>
      </div>
      {fotosNovas > 0 && (                       /* 187: foto chegada depois do download */
        <p className="jdb-final-aviso" role="status" style={{ background: '#EEF4FF', borderColor: '#18283B' }}>
          Chegaram fotos novas depois do download: estão em Detalhes › Imagens do laudo. Coloque no seu Word.
          {verFotos && <> <button type="button" className="btn-sec btn-peq" style={{ marginLeft: 6 }} onClick={verFotos}>Ver as fotos novas</button></>}
        </p>
      )}
      <CaixaEntrega jobId={job.id} />
    </section>
  )
}
