#!/usr/bin/env bash
# Dependências de SISTEMA do João de Barro (/api/avaliacao): LibreOffice converte o laudo
# Word em PDF e a planilha P2 (recalcula fórmulas). Idempotente: se o soffice já existe,
# não faz nada. Roda na VPS (Debian/Ubuntu) como root — o deploy_vps.sh chama este script.
#
#   bash scripts/avaliacao_deps.sh
#
# Pacotes: libreoffice-writer/calc (soffice), fonts-liberation (métricas Arial/Times do
# modelo), python3-uno (atualiza o sumário do laudo antes de gerar o PDF; sem ele o PDF
# sai igual, só que com o sumário sem atualizar).
# As dependências Python (pip install -r backend/requirements.txt) já são instaladas pelo
# deploy, no venv do backend.
set -euo pipefail

if command -v soffice >/dev/null 2>&1; then
  echo "[avaliacao_deps] LibreOffice já instalado: $(soffice --version 2>/dev/null | head -n1)"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "[avaliacao_deps] ERRO: apt-get não encontrado — instale LibreOffice Writer/Calc manualmente" >&2
  exit 1
fi

echo "[avaliacao_deps] instalando LibreOffice (writer, calc), fontes e python3-uno"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || true   # índice desatualizado não impede instalar do cache
apt-get install -y -qq -o DPkg::Lock::Timeout=120 --no-install-recommends \
  libreoffice-writer libreoffice-calc fonts-liberation python3-uno
echo "[avaliacao_deps] pronto: $(soffice --version 2>/dev/null | head -n1)"
