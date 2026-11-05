# -*- coding: utf-8 -*-
"""Fonte de dados do projeto: devolve df_estab e df_indic.

Por padrão lê os JSONs versionados em data/ (modo local, sem rede e sem
credenciais). Se a variável de ambiente MONGO_URI estiver definida, lê
do MongoDB Atlas (banco "saude_campinas", coleções regioes,
estabelecimentos e relacoes).

A reconstrução dos DataFrames segue a mesma lógica de celula_atlas.py e
da Etapa 5 do pipeline original; só mudou a origem dos documentos.
Este módulo NÃO depende de google.colab. No Colab, quem quiser usar o
secret pode passar o valor explicitamente:

    from google.colab import userdata
    df_estab, df_indic = carregar_dados(mongo_uri=userdata.get("MONGO_URI"))
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
NOME_BANCO = "saude_campinas"
COLECOES = ("regioes", "estabelecimentos", "relacoes")


# ─── Modo local: JSONs em data/ ──────────────────────────────────────
def _ler_docs_locais(data_dir=None):
    data_dir = Path(data_dir) if data_dir else DATA_DIR
    docs = {}
    for nome in COLECOES:
        caminho = data_dir / f"{nome}.json"
        docs[nome] = json.loads(caminho.read_text(encoding="utf-8"))
    return docs


# ─── Modo Atlas: MongoDB ─────────────────────────────────────────────
def _escapar_uri(mongo_uri):
    """Escapa usuário/senha (RFC 3986), como no pipeline original."""
    m = re.match(r"(mongodb(?:\+srv)?://)([^:]+):([^@]+)@(.+)", mongo_uri)
    if m:
        schema, user, password, rest = m.groups()
        mongo_uri = f"{schema}{quote_plus(user)}:{quote_plus(password)}@{rest}"
    return mongo_uri


def _ler_docs_atlas(mongo_uri):
    # Importado aqui para o modo local não exigir pymongo/certifi.
    import certifi
    from pymongo import MongoClient

    client = MongoClient(
        _escapar_uri(mongo_uri),
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=15000,
    )
    client.admin.command("ping")
    db = client[NOME_BANCO]
    return {nome: list(db[nome].find({})) for nome in COLECOES}


# ─── API pública ─────────────────────────────────────────────────────
def carregar_documentos(mongo_uri=None, data_dir=None):
    """Devolve {'regioes': [...], 'estabelecimentos': [...], 'relacoes': [...]}.

    Ordem de decisão: argumento mongo_uri > variável de ambiente
    MONGO_URI > JSONs locais em data/.
    """
    mongo_uri = mongo_uri or os.environ.get("MONGO_URI")
    if mongo_uri:
        return _ler_docs_atlas(mongo_uri)
    return _ler_docs_locais(data_dir)


def fonte_em_uso(mongo_uri=None):
    """Texto curto dizendo de onde os dados estão sendo lidos."""
    if mongo_uri or os.environ.get("MONGO_URI"):
        return f"MongoDB Atlas (banco {NOME_BANCO})"
    return "arquivos locais (data/*.json)"


def montar_df_estab(docs_estab):
    return pd.DataFrame([{
        "codigo_cnes":            d["_id"],
        "nome_fantasia":          d["nome"],
        "codigo_tipo_unidade":    d["tipo"]["codigo"],
        "descricao_tipo_unidade": d["tipo"]["descricao"],
        "categoria":              d["tipo"]["categoria"],
        "bairro_estabelecimento": d["endereco"]["bairro"],
        "regiao":                 d["endereco"]["regiao"],
        "latitude":               d["localizacao"]["coordinates"][1],
        "longitude":              d["localizacao"]["coordinates"][0],
        "vinculo_sus":            "SIM" if d["vinculo_sus"] else "NAO",
        "natureza":               d["natureza"],
    } for d in docs_estab])


def montar_df_indic(docs_reg):
    return pd.DataFrame([{
        "regiao":          d["regiao"],
        "populacao":       d["populacao"],
        "UBS":             d["unidades"]["ubs"],
        "Hospital":        d["unidades"]["hospital"],
        "UPA":             d["unidades"]["upa"],
        "total_unidades":  d["unidades"]["total"],
        "lat":             d["centroide"]["coordinates"][1],
        "lon":             d["centroide"]["coordinates"][0],
        "hab_por_ubs":     d["indicadores"]["hab_por_ubs"],
        "cobertura":       d["indicadores"]["cobertura"],
    } for d in docs_reg]).sort_values(
        "hab_por_ubs", ascending=False
    ).reset_index(drop=True)


def carregar_dados(mongo_uri=None, data_dir=None):
    """Devolve (df_estab, df_indic) a partir de data/*.json ou do Atlas."""
    docs = carregar_documentos(mongo_uri=mongo_uri, data_dir=data_dir)
    return montar_df_estab(docs["estabelecimentos"]), montar_df_indic(docs["regioes"])


if __name__ == "__main__":
    df_estab, df_indic = carregar_dados()
    print(f"Fonte: {fonte_em_uso()}")
    print(f"df_estab: {len(df_estab)} linhas | df_indic: {len(df_indic)} regiões")
