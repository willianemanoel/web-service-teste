"""
API do Portal de Tarefas Pendentes.

Endpoints:
    GET /api/tarefas?unidade=GOIAS
        Retorna { "atualizado_em": "...", "tarefas": [ {...}, ... ] }
        com os mesmos nomes de campo que o frontend já espera
        (CodCliente, RazaoSocial, Departamento, DataVencimento, etc.)

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

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Defina a variável de ambiente DATABASE_URL")

app = FastAPI(title="API Portal de Tarefas Pendentes")

# TODO: restringir allow_origins ao domínio real do frontend em produção,
# em vez de "*". Ex: ["https://portal-tarefas.onrender.com"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


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
WHERE c.unidade = %s
"""

QUERY_ULTIMA_ATUALIZACAO = """
SELECT GREATEST(MAX(t.atualizado_em), MAX(c.atualizado_em))
FROM tarefas_pendentes t
JOIN clientes c ON c.cod_cliente = t.cod_cliente
WHERE c.unidade = %s
"""


def serializar(valor):
    if isinstance(valor, (dt.datetime, dt.date)):
        return valor.isoformat()
    return valor


@app.get("/api/tarefas")
def listar_tarefas(unidade: str = Query(..., description="Ex: GOIAS, SP, RJ, Santos")):
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(QUERY_TAREFAS, (unidade,))
            linhas = cur.fetchall()

        with conn.cursor() as cur:
            cur.execute(QUERY_ULTIMA_ATUALIZACAO, (unidade,))
            resultado = cur.fetchone()
            ultima_atualizacao = resultado[0] if resultado else None
    finally:
        conn.close()

    tarefas = [{k: serializar(v) for k, v in linha.items()} for linha in linhas]

    return {
        "atualizado_em": serializar(ultima_atualizacao),
        "tarefas": tarefas,
    }


@app.get("/api/atualizacao")
def ultima_atualizacao_geral():
    """Retorna só a data da última atualização, sem carregar nenhuma tarefa —
    usado pra alimentar o aviso do topo da página sem precisar buscar
    os dados pesados de todas as unidades."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT GREATEST(MAX(t.atualizado_em), MAX(c.atualizado_em)) FROM tarefas_pendentes t JOIN clientes c ON c.cod_cliente = t.cod_cliente")
            resultado = cur.fetchone()
    finally:
        conn.close()
    return {"atualizado_em": serializar(resultado[0] if resultado else None)}


@app.get("/api/health")
def health():
    return {"status": "ok"}
