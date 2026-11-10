# João de Barro — Coletor (Windows)

Programinha que fica no seu PC e, quando o João de Barro precisa de anúncios de mercado
(ZAP, Viva Real, OLX, Imovelweb) ou do Google Maps, abre essas páginas no **seu Google Chrome**,
lê o conteúdo e manda de volta para o laudo. Ele não resolve captcha: se um portal pedir
verificação, aquele portal é pulado no trabalho e aparece um aviso.

## Instalação (uma vez)

1. Tenha o **Google Chrome** instalado.
2. No João de Barro, abra **Configurações → Coletor** e clique em **Baixar o Coletor**
   (`joaodebarro-coletor.exe`). Salve, por exemplo, em `Documentos`.
3. Na mesma tela, clique em **Gerar código de pareamento** — aparece um código de 8 letras (vale 10 minutos).
4. Dê dois cliques no `joaodebarro-coletor.exe`. Se o Windows mostrar "O Windows protegeu o
   computador", clique em **Mais informações → Executar assim mesmo**.
5. Na janelinha que abrir, **cole o código** e confirme. Pronto: o ícone (casinha) aparece perto
   do relógio e fica verde quando conectado; em Configurações → Coletor o status vira "online".
6. Para ele iniciar sozinho com o Windows, abra o Prompt e rode uma vez:
   `"%USERPROFILE%\Documents\joaodebarro-coletor.exe" --instalar-autostart`

## No dia a dia

- **Deixe o PC ligado e o coletor aberto** enquanto houver trabalhos rodando. Ele abre uma janela
  do Chrome própria (perfil separado do seu Chrome normal): não feche essa janela no meio de uma busca.
- Ele vai devagar de propósito (4 a 9 s entre páginas, no máximo 40 páginas e 20 anúncios por trabalho).
- Ícone na bandeja: mostra **Conectado/Desconectado**, **Abrir pasta de logs** e **Sair**.
- Se a internet cair, ele reconecta sozinho (tenta em 1, 5, 15 e depois a cada 60 s).

## Problemas comuns

- **Pediu o código de novo / "não foi possível parear":** gere um código novo em Configurações →
  Coletor (cada código vale uma vez e por 10 min). Para forçar novo pareamento: `--parear`.
- **Status offline:** veja se o ícone está na bandeja; senão, abra o `.exe` de novo.
- **Logs e configuração:** `%LOCALAPPDATA%\JoaoDeBarro\` (`config.json`, `logs\coletor.log`,
  `perfil-chrome\`). Apagar `config.json` desfaz o pareamento.

## Para desenvolvedores

```powershell
python -m pip install -r requirements.txt pytest
python -m pytest -q                               # offline (páginas locais + WS falso); precisa do Chrome
python joaodebarro_coletor.py --servidor http://127.0.0.1:8870   # servidor de dev
./build.ps1 [-Publicar]                           # gera dist\joaodebarro-coletor.exe
```

Segurança: só abre URLs de `zapimoveis.com.br`, `vivareal.com.br`, `olx.com.br`, `imovelweb.com.br`,
`google.com/maps`, `google.com.br/maps` e `maps.app.goo.gl` (tarefa com outra URL é recusada com
`"url não permitida"`); só fala com o servidor configurado; a 1ª foto do anúncio é baixada pelo
próprio coletor (https, só do portal/CDN dele, até 5 MB, 20 s, convertida para JPEG se vier WebP).
