# João de Barro

Motor de avaliação de imóveis: o avaliador envia os documentos e as fotos da vistoria, e o
sistema devolve o laudo em **Word + PDF + planilha de cálculo**, pronto para revisão e
assinatura.

Método comparativo direto de dados de mercado (Opinião de Valor, PTAM, PTAM de garantia e
PTAM judicial).

## Como funciona

1. **Triagem e extração** — a IA lê matrícula, IPTU, fotos e documentos do solicitante. Todo
   campo carrega a origem (documento, vistoria, pendente) e a fonte; informação verbal não
   entra no laudo.
2. **Pesquisa de referenciais** — o **Coletor**, um programa no PC do avaliador, abre os
   portais imobiliários no Chrome dele e manda os anúncios para o servidor por WebSocket.
3. **Seleção** — a IA escolhe e justifica; as regras objetivas são código: descarte de fora da
   curva (quartis ± 1,5·IQR por tipologia), amostra mínima, anúncio velho.
4. **Cálculo** — determinístico (`Decimal`), igual na tela, no Word e na planilha.
5. **Redação e montagem** — textos das seções pela IA, sobre modelos Word; PDF pelo
   LibreOffice.
6. **Revisão** — conferência de matemática e diagramação em código, mais um revisor de IA que
   devolve a etapa responsável com o motivo.
7. **Entrega** — status (pronto / parcial / bloqueado) e pendências acionáveis na tela.

O pipeline é retomável: cada etapa grava o resultado como evento, e refazer uma etapa
invalida as seguintes.

## Onde fica o quê

| Caminho | O quê |
|---|---|
| `backend/lovable/avaliacao/` | rotas FastAPI, orquestrador, banco (SQLite), cálculo, Word/PDF/planilha |
| `backend/lovable/avaliacao/agentes/` | triagem, extração, pesquisa, seleção, redação, revisor |
| `backend/tests/avaliacao/` | suíte (pytest) |
| `frontend/src/joaodebarro/` | tela do avaliador (React + Tailwind) |
| `coletor/` | programa de bandeja para Windows (Playwright dirigindo o Chrome) |

## Sobre este repositório

É um recorte para leitura. O João de Barro roda dentro de uma aplicação maior (autenticação,
configuração e contas de IA vêm dela), então **não sobe sozinho** a partir daqui.

Os laudos reais usados como referência de estilo foram retirados, e os nomes e o endereço do
caso-modelo que aparecem em testes e exemplos foram trocados por fictícios. Por isso alguns
testes que dependem desses arquivos não passam neste recorte.
