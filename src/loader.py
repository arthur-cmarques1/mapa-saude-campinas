# -*- coding: utf-8 -*-
"""Fonte de dados do projeto: devolve df_estab, df_indic e os metadados.

Por padrão lê os JSONs de data/ (sem rede e sem credenciais). Se houver
MONGO_URI (argumento, variável de ambiente ou arquivo .env na raiz), tenta ler
do MongoDB. Se o banco falhar ou estiver desatualizado, avisa e usa os arquivos
locais, para o painel nunca deixar de funcionar por causa de uma credencial.
"""

import json
import os
import re
import sys
import warnings
from pathlib import Path
from urllib.parse import quote, unquote

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
NOME_BANCO = "saude_campinas"
COLECOES = ("regioes", "estabelecimentos", "relacoes")
VERSAO_ESQUEMA = 2


# ─── Configuração ────────────────────────────────────────────────────
def obter_uri(mongo_uri=None, arquivo_env=None):
    """Ordem: argumento > variável de ambiente > arquivo .env na raiz."""
    if mongo_uri:
        return mongo_uri.strip()
    if os.environ.get("MONGO_URI", "").strip():
        return os.environ["MONGO_URI"].strip()
    arquivo_env = Path(arquivo_env) if arquivo_env else RAIZ / ".env"
    if arquivo_env.is_file():
        for linha in arquivo_env.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:export\s+)?MONGO_URI\s*=\s*(.*)$", linha)
            if m:
                return m.group(1).strip().strip("'\"") or None
    return None


# ─── Modo local: JSONs em data/ ──────────────────────────────────────
def _ler_docs_locais(data_dir=None):
    data_dir = Path(data_dir) if data_dir else DATA_DIR
    docs = {}
    for nome in (*COLECOES, "metadados"):
        caminho = data_dir / f"{nome}.json"
        try:
            docs[nome] = json.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError as erro:
            raise FileNotFoundError(
                f"Arquivo de dados não encontrado: {caminho}. "
                "Baixe o projeto completo ou rode: python src/pipeline.py"
            ) from erro
    return docs


# ─── Modo MongoDB ────────────────────────────────────────────────────
def _escapar_uri(mongo_uri):
    """Escapa usuário e senha sem escapar duas vezes o que já veio escapado.

    A senha pode conter '@' ou ':'; por isso o host é o que vem depois do
    último '@' e o usuário é o que vem antes do primeiro ':'.
    """
    m = re.match(r"(mongodb(?:\+srv)?://)(.+)@([^@]+)$", mongo_uri)
    if not m:
        return mongo_uri
    esquema, credenciais, resto = m.groups()
    usuario, separador, senha = credenciais.partition(":")
    usuario = quote(unquote(usuario), safe="")
    if not separador:
        return f"{esquema}{usuario}@{resto}"
    return f"{esquema}{usuario}:{quote(unquote(senha), safe='')}@{resto}"


def _ocultar_senha(texto):
    """Tira credenciais de mensagens de erro, que podem ir parar em logs."""
    return re.sub(r"(mongodb(?:\+srv)?://)[^\s/]*@", r"\1***@", str(texto))


def conectar(mongo_uri):
    """Abre a conexão e confirma com ping. O CA do certifi só vale para TLS (+srv)."""
    from pymongo import MongoClient

    opcoes = {"serverSelectionTimeoutMS": 15000}
    if mongo_uri.startswith("mongodb+srv://"):
        import certifi

        opcoes["tlsCAFile"] = certifi.where()
    client = MongoClient(_escapar_uri(mongo_uri), **opcoes)
    try:
        client.admin.command("ping")
    except Exception:
        client.close()
        raise
    return client


def _ler_docs_atlas(mongo_uri):
    client = conectar(mongo_uri)
    try:
        db = client[NOME_BANCO]
        docs = {nome: list(db[nome].find({})) for nome in COLECOES}
        metadados = db["metadados"].find_one({"_id": "painel"})
    finally:
        client.close()
    if not metadados or metadados.get("versao_esquema") != VERSAO_ESQUEMA:
        raise ValueError("o banco ainda está no formato antigo; "
                         "rode: python src/pipeline.py --carregar-atlas --confirmar")
    if not all(docs[nome] for nome in COLECOES):
        raise ValueError("o banco tem coleções vazias")
    docs["metadados"] = metadados
    return docs


# ─── API pública ─────────────────────────────────────────────────────
def carregar_documentos(mongo_uri=None, data_dir=None):
    """Devolve {'regioes', 'estabelecimentos', 'relacoes', 'metadados'}."""
    uri = obter_uri(mongo_uri)
    if uri:
        try:
            return _ler_docs_atlas(uri)
        except Exception as erro:  # o painel não pode depender do banco estar acessível
            warnings.warn(f"MongoDB indisponível ({_ocultar_senha(erro)}). "
                          "Usando os arquivos locais em data/.", stacklevel=2)
    return _ler_docs_locais(data_dir)


def fonte_em_uso(mongo_uri=None):
    """Texto curto com a fonte configurada (a leitura ainda pode cair nos arquivos)."""
    if obter_uri(mongo_uri):
        return f"MongoDB (banco {NOME_BANCO}), com os arquivos locais como reserva"
    return "arquivos locais (data/*.json)"


def montar_df_estab(docs_estab):
    return pd.DataFrame([{
        "codigo_cnes":            d["_id"],
        "nome_fantasia":          d["nome"],
        "codigo_tipo_unidade":    d["tipo"]["codigo"],
        "descricao_tipo_unidade": d["tipo"]["descricao"],
        "categoria":              d["tipo"]["categoria"],
        "logradouro":             d["endereco"]["logradouro"],
        "numero":                 d["endereco"]["numero"],
        "bairro_estabelecimento": d["endereco"]["bairro"],
        "cep":                    d["endereco"]["cep"],
        "regiao":                 d["endereco"]["regiao"],
        "regiao_origem":          d["endereco"]["regiao_origem"],
        "latitude":               d["localizacao"]["coordinates"][1],
        "longitude":              d["localizacao"]["coordinates"][0],
        "telefone":               d["telefone"],
        "turno":                  d["turno"],
        "vinculo_sus":            "SIM" if d["vinculo_sus"] else "NAO",
        "natureza":               d["natureza"],
        "atualizado_em":          d["atualizado_em"],
        "equipes":                d["equipes"],
    } for d in docs_estab])


def montar_df_indic(docs_reg):
    return pd.DataFrame([{
        "regiao":                 d["regiao"],
        "populacao":              d["populacao"],
        "UBS":                    d["unidades"]["ubs"],
        "Hospital":               d["unidades"]["hospital"],
        "UPA":                    d["unidades"]["upa"],
        "hospital_sem_sus":       d["unidades"]["hospital_sem_sus"],
        "total_unidades":         d["unidades"]["total"],
        "lat":                    d["centroide"]["coordinates"][1],
        "lon":                    d["centroide"]["coordinates"][0],
        "equipes":                d["indicadores"]["equipes"],
        "populacao_cadastrada":   d["indicadores"]["populacao_cadastrada"],
        "hab_por_ubs":            d["indicadores"]["hab_por_ubs"],
        "hab_por_equipe":         d["indicadores"]["hab_por_equipe"],
        "cadastrados_por_equipe": d["indicadores"]["cadastrados_por_equipe"],
        "pressao":                d["indicadores"]["pressao"],
        "nivel":                  d["indicadores"]["nivel"],
    } for d in docs_reg]).sort_values(
        "pressao", ascending=False
    ).reset_index(drop=True)


def carregar_dados(mongo_uri=None, data_dir=None):
    """Devolve (df_estab, df_indic) a partir de data/*.json ou do MongoDB."""
    docs = carregar_documentos(mongo_uri=mongo_uri, data_dir=data_dir)
    return montar_df_estab(docs["estabelecimentos"]), montar_df_indic(docs["regioes"])


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    df_estab, df_indic = carregar_dados()
    print(f"Fonte: {fonte_em_uso()}")
    print(f"df_estab: {len(df_estab)} linhas | df_indic: {len(df_indic)} regiões")
