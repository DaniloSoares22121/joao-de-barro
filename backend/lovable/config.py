"""Configuração local (substitui a config do Brixly). Tudo ajustável por variável de ambiente."""
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("LOVABLE_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Modelos usados pelo claude_agent_sdk (login do Claude Code nesta máquina ou ANTHROPIC_API_KEY)
# ORDEM 071-C2: o melhor modelo nas etapas que pensam (o Alan escolheu "sem teto" de custo)
MODEL = os.environ.get("LOVABLE_MODEL") or "claude-opus-5-5"
LIGHT_MODEL = os.environ.get("LOVABLE_LIGHT_MODEL") or "claude-haiku-5-5"
FALLBACK_MODEL = os.environ.get("LOVABLE_FALLBACK_MODEL") or None
ESFORCO = os.environ.get("LOVABLE_ESFORCO") or ""
# ORDEM 075 / D-117 / 112: não há pesquisa automática nos portais. O caminho é o Chrome do avaliador
# (extensão "Enviar ao JdB") ou o cadastro à mão.
CLAUDE_CLI = os.environ.get("LOVABLE_CLAUDE_CLI") or None
