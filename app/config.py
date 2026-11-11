"""Configuração única do sistema. Tudo que muda o comportamento do modelo vive aqui
(e é gravado no traço de cada resposta), para que uma execução possa ser repetida."""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
INDEX_DIR = RAIZ / "index"
TRACOS_DIR = Path(os.getenv("TRACOS_DIR", RAIZ / "resultados" / "tracos"))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# Modelos remotos (opt-in). A chave fica fora do repositório: config/conexoes.json (permissão 600) ou variável de ambiente.
CONEXOES_ARQ = Path(os.getenv("CONEXOES_ARQ", RAIZ / "config" / "conexoes.json"))
# CONEXOES_LOCAL=1: trata o servidor como local mesmo quando o cliente chega por IP da ponte (docker run -p). Nunca no deploy público.
CONEXOES_LOCAL = os.getenv("CONEXOES_LOCAL") == "1"
TIMEOUT_REMOTO_S = float(os.getenv("TIMEOUT_REMOTO_S", "120"))
# CHAVE_DO_USUARIO=1 (servidor compartilhado): cada pessoa traz a própria chave, enviada a cada pergunta no cabeçalho
# X-Chave-Remoto. O servidor ignora DEEPSEEK_API_KEY e config/conexoes.json e nunca grava a chave recebida.
CHAVE_DO_USUARIO = os.getenv("CHAVE_DO_USUARIO") == "1"
# ACESSO_SENHA: se definida, toda a API (exceto /api/entrar) exige a senha compartilhada (cookie assinado).
ACESSO_SENHA = os.getenv("ACESSO_SENHA", "")

# Modelos fixos durante cada comparação (Etapa 2 do projeto).
MODELO_LLM = os.getenv("MODELO_LLM", "qwen3.5:4b-q4_K_M")
MODELO_EMBED = os.getenv("MODELO_EMBED", "bge-m3")
MODELOS_PERMITIDOS = [m.strip() for m in os.getenv("MODELOS_PERMITIDOS", "qwen3.5:4b-q4_K_M,gemma4:e4b-it-q4_K_M").split(",") if m.strip()]

# Experimentos de segmentação (Etapa 3). tokens=None -> segmentação por seção.
EXPERIMENTOS = {
    "E1": {"tokens": 256, "sobreposicao": 0.10, "top_k": 3},
    "E2": {"tokens": 512, "sobreposicao": 0.15, "top_k": 5},
    "E3": {"tokens": 1024, "sobreposicao": 0.20, "top_k": 5},
    "E4": {"tokens": None, "sobreposicao": 0.0, "top_k": 5},
}
EXPERIMENTO = os.getenv("EXPERIMENTO", "E2")

# Condições de corpus (Etapa 7). C4 é o corpus completo usado na demonstração.
CONDICOES = {
    "C1": ["BNCC"],
    "C2": ["BNCC", "RAMLI"],
    "C3": ["BNCC", "RAMLI", "HALL"],
    "C4": ["BNCC", "ABC", "RAMLI", "HALL", "ROSA", "PNEEI", "HE1", "HE2", "HE3"],
    # Experimento à parte: C4 + resumos de vídeo do YouTube feitos pelo grupo (legenda automática resumida por IA).
    # A demonstração continua em C4.
    "C5": ["BNCC", "ABC", "RAMLI", "HALL", "ROSA", "PNEEI", "HE1", "HE2", "HE3", "VID"],
}
CONDICAO = os.getenv("CONDICAO", "C4")

# Context engineering: orçamento da janela.
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))
ORCAMENTO_CONTEXTO = int(os.getenv("ORCAMENTO_CONTEXTO", "3200"))  # tokens de trechos recuperados
CANDIDATOS = int(os.getenv("CANDIDATOS", "20"))  # candidatos de cada busca antes da fusão
RRF_K = 60
MAX_RESPOSTA = int(os.getenv("MAX_RESPOSTA", "900"))
TEMPERATURA = float(os.getenv("TEMPERATURA", "0.2"))

# Harness: limiar de cobertura (similaridade de cosseno do melhor trecho, bge-m3).
LIMIAR_COBERTURA = float(os.getenv("LIMIAR_COBERTURA", "0.55"))
MAX_PERGUNTA_CHARS = 1200


def aprox_tokens(texto: str) -> int:
    """Aproximação usada em todo o sistema: ~4 caracteres por token."""
    return max(1, len(texto) // 4)
