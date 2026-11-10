# João de Barro

Motor de avaliação de imóveis: o avaliador envia os documentos e as fotos da vistoria, e o
sistema devolve o laudo em **Word + PDF + planilha de cálculo**, pronto para revisão e
assinatura.

Método comparativo direto de dados de mercado (Opinião de Valor, PTAM, PTAM de garantia e
PTAM judicial).

## Rodar neste computador (Windows)

1. Baixe o repositório (`git clone` ou "Code > Download ZIP" e extraia).
2. Clique com o botão direito em **`iniciar.ps1`** > **Executar com o PowerShell**
   (ou, num terminal na pasta: `powershell -ExecutionPolicy Bypass -File .\iniciar.ps1`).

O script instala o Python e o Node se faltarem, instala as bibliotecas, gera a tela, pede o
e-mail e a senha do avaliador na primeira vez e abre **http://127.0.0.1:8870**. Rodar de novo
só sobe o servidor.

Se o script instalar o Python ou o Node e depois disser que não encontrou, feche a janela,
abra outra e rode de novo (o Windows só enxerga o programa novo numa janela nova).

### O que precisa estar configurado para gerar laudo

| O quê | Para quê | Como |
|---|---|---|
| **IA (Claude)** | ler documentos, selecionar referenciais, redigir e revisar | copie `.env.exemplo` para `.env` e preencha `ANTHROPIC_API_KEY`; ou instale o Claude Code neste PC e faça login (aí usa a assinatura) |
| **Coletor** | pesquisar os anúncios nos portais pelo Chrome deste PC | veja abaixo |
| **LibreOffice** | gerar o PDF do laudo | `winget install TheDocumentFoundation.LibreOffice` (sem ele sai só Word e planilha) |
| **Google Chrome** | o Coletor dirige o Chrome | instalado normalmente |

Sem a IA configurada a tela abre e aceita os arquivos, mas o trabalho termina com a pendência
"IA falhou".

### Coletor

Na tela: **Configurações > Coletor > Gerar código de pareamento**. Depois abra o Coletor
apontando para este servidor e cole o código:

```
data\avaliacao\coletor\joaodebarro-coletor.exe --servidor http://127.0.0.1:8870 --parear
```

O `iniciar.ps1` baixa esse `.exe` da página de Releases, e o botão "Baixar o Coletor" da tela
entrega o mesmo arquivo. Sem o `--servidor`, o Coletor procura o servidor de produção.

Para rodar o Coletor pelo código em vez do `.exe`:

```
cd coletor
pip install -r requirements.txt
python joaodebarro_coletor.py --servidor http://127.0.0.1:8870 --parear
```

### Outros comandos

```
backend\.venv\Scripts\python backend\criar_usuario.py email senha   # cria o avaliador ou troca a senha
cd backend && .venv\Scripts\python -m pytest tests -q                 # testes do servidor
cd frontend && npm test                                               # testes da tela
```

Os dados (banco, arquivos enviados e laudos) ficam na pasta `data/`. Para acessar de outro
aparelho da rede, ponha `JDB_HOST=0.0.0.0` no `.env` — só em rede de confiança: não há HTTPS.

## Como funciona

1. **Triagem e extração** — a IA lê matrícula, IPTU, fotos e documentos do solicitante. Todo
   campo carrega a origem (documento, vistoria, pendente) e a fonte; informação verbal não
   entra no laudo.
2. **Pesquisa de referenciais** — o **Coletor** abre os portais imobiliários no Chrome do
   avaliador e manda os anúncios para o servidor por WebSocket.
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
| `backend/lovable/avaliacao/` | rotas, orquestrador, banco (SQLite), cálculo, Word/PDF/planilha |
| `backend/lovable/avaliacao/agentes/` | triagem, extração, pesquisa, seleção, redação, revisor |
| `backend/lovable/*.py` | servidor: arranque, login, configuração |
| `backend/tests/` | suíte (pytest) |
| `frontend/src/joaodebarro/` | tela do avaliador (React + Tailwind) |
| `coletor/` | programa de bandeja para Windows (Playwright dirigindo o Chrome) |

## Sobre os exemplos

Os laudos reais usados como referência de estilo na redação (`A1`, `A2`, `P8`) têm dados de
clientes e ficam fora do repositório; sem eles a redação usa trechos anonimizados
(`exemplos_secoes.json`). Quem tiver os arquivos pode copiá-los para
`backend/lovable/avaliacao/assets/conhecimento/` — eles estão no `.gitignore`. Nomes e
endereço do caso-modelo que aparecem em testes e exemplos são fictícios.
