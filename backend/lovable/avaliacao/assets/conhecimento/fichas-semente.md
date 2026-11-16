# Fichas-semente da base de conhecimento (D-058 / D-061)

Autor: João de Barro, 12/11/2026. Todas protegidas: sem nomes, endereços, matrículas, inscrições, links ou valores exatos.
Formato de cada ficha: id, título, tipo (regra | caso | modelo), nível (oficial | validado | aprendido), escopo (geral | avaliador), etiquetas (tipo_imovel; modalidade; etapa), situação, decisão, porquê, fonte.
Importar como está. O nível já está decidido (estas foram aprovadas pelo Alan, que é o curador).

---

### F-S001 — Objeto é só uma parte do lote
- tipo: caso | nível: validado | escopo: geral
- etiquetas: tipo_imovel=galpão, comercial; modalidade=OV, AM, AMJ; etapa=documentos, áreas, cálculo
- situação: o cadastro municipal traz a área edificada do lote inteiro (vários prédios), mas o objeto da avaliação é um só galpão dentro dele.
- decisão: usar a área do objeto (medida por satélite quando não houver documento, D-027), mostrar ao avaliador as duas áreas (a do cadastro e a do objeto), já com a do objeto marcada, e só calcular depois do ok dele.
- porquê: com a área do lote inteiro o valor saiu cerca de 3 vezes maior que o laudo oficial.
- fonte: D-059; D-027; trabalho de teste de 12/11/2026

### F-S002 — Base do cálculo: área construída ou área total
- tipo: regra | nível: validado | escopo: geral
- etiquetas: tipo_imovel=todos; modalidade=OV, AM, AMJ; etapa=cálculo
- situação: chegou a hora de multiplicar o unitário (R$/m²) pela área.
- decisão: perguntar sempre se o cálculo é pela área construída ou pela área total do terreno. Quando os comparativos têm lotes parecidos com o do avaliando, o normal é usar só a área construída, mas a decisão é do avaliador.
- porquê: a base muda o resultado inteiro e depende do mercado e das amostras de cada caso.
- fonte: D-059

### F-S003 — A área do anúncio pode ser a do terreno
- tipo: caso | nível: validado | escopo: geral
- etiquetas: tipo_imovel=galpão, lote, casa; modalidade=OV, AM, AMJ; etapa=pesquisa, cálculo
- situação: em galpão, o "m²" do cartão do portal às vezes é a área do terreno, e não a construída (ex.: cartão com área cerca de 45% maior que a construída real).
- decisão: abrir o anúncio e conferir no texto qual área é, antes de calcular o R$/m² da amostra. Na dúvida, marcar a amostra como "área a conferir".
- porquê: com a área errada o unitário da amostra cai cerca de 30% e puxa o valor do avaliando para baixo.
- caso (13/11/2026): avaliação de galpão com 6 amostras de portal; em 2 o cartão trazia o terreno e em outras 2 o anúncio se contradizia (preço ou área). Com a área construída do texto, a média da amostra subiu cerca de 33% e a dispersão passou de 25%. O sistema agora confere a área do cartão contra o texto do anúncio e avisa.
- fonte: trabalho de teste de 12/11/2026; caso confirmado em 13/11/2026

### F-S004 — Amostra dispersa: dizer quem espalha
- tipo: regra | nível: validado | escopo: geral
- etiquetas: tipo_imovel=todos; modalidade=OV, AM, AMJ; etapa=cálculo
- situação: o coeficiente de variação das amostras passou de 15%.
- decisão: o alerta diz quais amostras, se retiradas, mais baixam o CV, e quanto fica o CV sem elas. Entre manter ou tirar, preferir manter a mais parecida com o avaliando (mesmo polo ou bairro, mesma tipologia) e tirar a de região ou tipologia diferente. A decisão é do avaliador.
- porquê: proximidade e tipologia pesam mais que a quantidade de amostras; alerta sem nome não ajuda a decidir.
- fonte: D-060; D-010

### F-S005 — Lista de candidatos ordenada, com o porquê
- tipo: regra | nível: validado | escopo: geral
- etiquetas: tipo_imovel=todos; modalidade=OV, AM, AMJ; etapa=pesquisa
- situação: a pesquisa trouxe os candidatos a referencial.
- decisão: mostrar do mais parecido para o menos parecido, cada um com "Por que indico" (bairro, tipologia, área ±%, padrão, idade); os descartados vão por último, com o motivo.
- porquê: o avaliador decide mais rápido e com o critério à vista.
- fonte: D-056; D-010; D-021

### F-S006 — Fotos e páginas: o sistema escolhe, sem limite de páginas
- tipo: regra | nível: validado | escopo: geral
- etiquetas: tipo_imovel=todos; modalidade=OV, AM, AMJ; etapa=fotos, redação, revisão
- situação: o avaliador subiu todas as fotos da vistoria e os documentos inteiros.
- decisão: escolher uma foto por ambiente ou ângulo (a mais nítida, sem repetidas, fachada sempre), legendar pela imagem, ordenar de fora para dentro, e anexar só as páginas de documento que importam (ex.: ficha da matrícula, 1ª página do IPTU). Não há limite de páginas; o revisor não reprova por número de páginas.
- porquê: o tamanho do laudo vem das escolhas, como o avaliador faz à mão.
- fonte: D-057; D-022

### F-S007 — Sem base, não inventa
- tipo: regra | nível: validado | escopo: geral
- etiquetas: tipo_imovel=todos; modalidade=todas; etapa=todas
- situação: pediram uma regra ou um modelo (ex.: laudo rural) para o qual não há fonte oficial nem ficha.
- decisão: responder que ainda não há base para isso, mostrar só o que vem da fonte oficial e sugerir aprender com o primeiro trabalho desse tipo.
- porquê: dado ou regra inventada vira erro no laudo e responsabilidade do avaliador.
- fonte: D-061; Instruções §2.1
