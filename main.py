"""
API do Portal de Tarefas Pendentes.

Endpoints:
    GET /api/atualizacao
        Retorna { "atualizado_em": "..." } — só a data, sem carregar
        nenhuma tarefa. Usado para o aviso do topo da página.

    GET /api/resumo?unidade=GOIAS
        Retorna contagens agregadas (não as linhas em si):
        {
          "atualizado_em": "...",
          "total": 774, "emAtraso": 19, "emAberto": 61, "baixadas": 694,
          "departamentos": [
            {"nome": "DP - DEPTO. PESSOAL", "total": 186, "emAtraso": 3, "emAberto": 10, "baixadas": 173},
            ...
          ]
        }
        Usado pela Tela 2 (cards de departamento) — nunca carrega as
        tarefas linha a linha, só números, então é leve mesmo para
        unidades com dezenas de milhares de tarefas.

    GET /api/tarefas?unidade=GOIAS&departamento=DP%20-%20DEPTO.%20PESSOAL
        Retorna { "atualizado_em": "...", "tarefas": [ {...}, ... ] }
        SÓ das tarefas daquele departamento específico — é isso que
        mantém o payload pequeno mesmo em unidades grandes (ex: SP,
        que tem ~58 mil tarefas no total, mas cada departamento
        individualmente é uma fração disso).

    GET /api/health
        Health check simples.

Rodar localmente:
    export DATABASE_URL=postgresql://usuario:senha@host/banco
    uvicorn main:app --reload

Deploy no Render:
    Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import os
import datetime as dt
from collections import defaultdict

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Defina a variável de ambiente DATABASE_URL")

app = FastAPI(title="API Portal de Tarefas Pendentes")

# TODO: restringir allow_origins ao domínio real do frontend em produção,
# em vez de "*". Ex: ["https://controladoria-mg.github.io"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def serializar(valor):
    if isinstance(valor, (dt.datetime, dt.date)):
        return valor.isoformat()
    return valor


# ── /api/atualizacao ──────────────────────────────────────
QUERY_ATUALIZACAO_GERAL = """
SELECT GREATEST(MAX(t.atualizado_em), MAX(c.atualizado_em))
FROM tarefas_pendentes t
JOIN clientes c ON c.cod_cliente = t.cod_cliente
"""


@app.get("/api/atualizacao")
def atualizacao_geral():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY_ATUALIZACAO_GERAL)
            resultado = cur.fetchone()
    finally:
        conn.close()
    return {"atualizado_em": serializar(resultado[0] if resultado else None)}


# ── /api/resumo ────────────────────────────────────────────
QUERY_RESUMO = """
SELECT t.departamento AS departamento, t.status AS status, COUNT(*) AS qtd
FROM tarefas_pendentes t
JOIN clientes c ON c.cod_cliente = t.cod_cliente
WHERE c.unidade = %s
GROUP BY t.departamento, t.status
"""

QUERY_ATUALIZACAO_UNIDADE = """
SELECT GREATEST(MAX(t.atualizado_em), MAX(c.atualizado_em))
FROM tarefas_pendentes t
JOIN clientes c ON c.cod_cliente = t.cod_cliente
WHERE c.unidade = %s
"""

CHAVE_STATUS = {"Em Atraso": "emAtraso", "Em Aberto": "emAberto", "Baixado": "baixadas"}


@app.get("/api/resumo")
def resumo_unidade(unidade: str = Query(..., description="Ex: GOIAS, SP, RJ, Santos")):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY_RESUMO, (unidade,))
            linhas = cur.fetchall()

        with conn.cursor() as cur:
            cur.execute(QUERY_ATUALIZACAO_UNIDADE, (unidade,))
            resultado = cur.fetchone()
            atualizado_em = resultado[0] if resultado else None
    finally:
        conn.close()

    departamentos = defaultdict(lambda: {"total": 0, "emAtraso": 0, "emAberto": 0, "baixadas": 0})
    geral = {"total": 0, "emAtraso": 0, "emAberto": 0, "baixadas": 0}

    for departamento, status, qtd in linhas:
        chave = CHAVE_STATUS.get(status)
        departamentos[departamento]["total"] += qtd
        geral["total"] += qtd
        if chave:
            departamentos[departamento][chave] += qtd
            geral[chave] += qtd

    lista_departamentos = [
        {"nome": nome, **contagens} for nome, contagens in departamentos.items()
    ]
    lista_departamentos.sort(key=lambda d: d["nome"])

    return {
        "atualizado_em": serializar(atualizado_em),
        **geral,
        "departamentos": lista_departamentos,
    }


# ── /api/tarefas ───────────────────────────────────────────
QUERY_TAREFAS = """
SELECT
    t.cod_baixa               AS "CodBaixa",
    t.cod_cliente              AS "CodCliente",
    c.razao_social              AS "RazaoSocial",
    c.unidade                    AS "Unidade",
    t.cod                         AS "Cod",
    t.cod_pai                     AS "CodPai",
    t.departamento                 AS "Departamento",
    t.titulo                        AS "Titulo",
    t.grupo                          AS "Grupo",
    t.classificacao                   AS "Classificacao",
    t.prioridade                       AS "Prioridade",
    t.status                            AS "Status",
    t.competencia                        AS "Competencia",
    t.data_vencimento                     AS "DataVencimento",
    t.data_previsao_conclusao              AS "DataPrevisaoConclusao",
    t.data_baixa                            AS "DataBaixa",
    t.dias_em_atraso                         AS "DiasEmAtraso",
    t.usuario_responsavel                     AS "UsuarioResponsavel",
    t.usuario_baixa                            AS "UsuarioBaixa",
    t.coordenador                               AS "Coordenador",
    t.comentario                                 AS "Comentario"
FROM tarefas_pendentes t
JOIN clientes c ON c.cod_cliente = t.cod_cliente
WHERE c.unidade = %s AND t.departamento = %s
"""


@app.get("/api/tarefas")
def listar_tarefas(
    unidade: str = Query(..., description="Ex: GOIAS, SP, RJ, Santos"),
    departamento: str = Query(..., description="Nome exato do departamento"),
):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(QUERY_TAREFAS, (unidade, departamento))
            linhas = cur.fetchall()

        with conn.cursor() as cur:
            cur.execute(QUERY_ATUALIZACAO_UNIDADE, (unidade,))
            resultado = cur.fetchone()
            atualizado_em = resultado[0] if resultado else None
    finally:
        conn.close()

    tarefas = [{k: serializar(v) for k, v in linha.items()} for linha in linhas]

    return {
        "atualizado_em": serializar(atualizado_em),
        "tarefas": tarefas,
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}
