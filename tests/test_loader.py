# -*- coding: utf-8 -*-
"""Leitura de dados e configuração do MongoDB, sem acessar nenhum servidor."""

import sys
import types
from urllib.parse import unquote

import pytest

import loader


@pytest.fixture(autouse=True)
def sem_uri(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setattr(loader, "RAIZ", tmp_path)


@pytest.mark.parametrize("senha", ["simples", "tem@arroba", "tem:dois", "tem/barra", "a+b", "50%off", "#?&"])
def test_senha_especial_chega_intacta(senha):
    uri = loader._escapar_uri(f"mongodb+srv://user:{senha}@host.mongodb.net/?retryWrites=true")
    credenciais = uri.split("://")[1].rsplit("@", 1)[0]
    assert unquote(credenciais.split(":")[1]) == senha
    assert uri.endswith("@host.mongodb.net/?retryWrites=true")


def test_senha_ja_escapada_nao_escapa_de_novo():
    assert loader._escapar_uri("mongodb://u:a%40b@h/") == "mongodb://u:a%40b@h/"


def test_uri_sem_credenciais_nao_muda():
    assert loader._escapar_uri("mongodb://localhost:27017/") == "mongodb://localhost:27017/"


def test_mensagem_de_erro_nao_vaza_senha():
    texto = loader._ocultar_senha("falhou em mongodb+srv://user:segredo@host/")
    assert "segredo" not in texto and "***" in texto


def test_prioridade_da_uri(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text('MONGO_URI="mongodb://arquivo/"\n', encoding="utf-8")
    assert loader.obter_uri(arquivo_env=env) == "mongodb://arquivo/"
    monkeypatch.setenv("MONGO_URI", "mongodb://ambiente/")
    assert loader.obter_uri(arquivo_env=env) == "mongodb://ambiente/"
    assert loader.obter_uri("mongodb://argumento/", arquivo_env=env) == "mongodb://argumento/"


@pytest.mark.parametrize("conteudo", ["MONGO_URI=\n", "# MONGO_URI=mongodb://x/\n", ""])
def test_env_vazio_ou_comentado_usa_modo_local(tmp_path, conteudo):
    env = tmp_path / ".env"
    env.write_text(conteudo, encoding="utf-8")
    assert loader.obter_uri(arquivo_env=env) is None


def test_modo_local_carrega_tudo():
    df_estab, df_indic = loader.carregar_dados()
    assert len(df_estab) == 99
    assert len(df_indic) == 6
    assert df_indic["pressao"].is_monotonic_decreasing


def test_arquivo_ausente_explica_o_que_fazer(tmp_path):
    with pytest.raises(FileNotFoundError, match="pipeline.py"):
        loader.carregar_documentos(data_dir=tmp_path)


def test_banco_inacessivel_avisa_e_usa_arquivos(monkeypatch):
    def falha(uri):
        raise ConnectionError(f"sem acesso a {uri}")
    monkeypatch.setattr(loader, "_ler_docs_atlas", falha)
    with pytest.warns(UserWarning, match="arquivos locais") as avisos:
        docs = loader.carregar_documentos(mongo_uri="mongodb://u:segredo@h/")
    assert len(docs["estabelecimentos"]) == 99
    assert "segredo" not in str(avisos[0].message)


class _Colecao(list):
    def find(self, _):
        return list(self)

    def find_one(self, _):
        return self[0] if self else None


def _cliente_falso(monkeypatch, colecoes):
    banco = types.SimpleNamespace(__getitem__=None)

    class Banco:
        def __getitem__(self, nome):
            return _Colecao(colecoes.get(nome, []))

    class Cliente:
        def __getitem__(self, nome):
            return Banco()

        def close(self):
            banco.fechado = True

    monkeypatch.setattr(loader, "conectar", lambda uri: Cliente())
    return banco


def test_banco_no_formato_antigo_e_recusado(monkeypatch):
    banco = _cliente_falso(monkeypatch, {"regioes": [{"regiao": "NORTE"}], "estabelecimentos": [{}], "relacoes": [{}]})
    with pytest.raises(ValueError, match="formato antigo"):
        loader._ler_docs_atlas("mongodb://h/")
    assert banco.fechado


def test_banco_atual_e_aceito(monkeypatch):
    colecoes = {"regioes": [{"r": 1}], "estabelecimentos": [{"e": 1}], "relacoes": [{"x": 1}],
                "metadados": [{"_id": "painel", "versao_esquema": loader.VERSAO_ESQUEMA}]}
    _cliente_falso(monkeypatch, colecoes)
    assert loader._ler_docs_atlas("mongodb://h/")["regioes"] == [{"r": 1}]


@pytest.mark.skipif("pymongo" not in sys.modules and not __import__("importlib.util").util.find_spec("pymongo"),
                    reason="pymongo não instalado")
def test_certificado_so_e_usado_com_srv(monkeypatch):
    import pymongo

    capturado = {}

    class Falso:
        def __init__(self, uri, **opcoes):
            capturado.update(opcoes)
            self.admin = types.SimpleNamespace(command=lambda _: {"ok": 1})

    monkeypatch.setattr(pymongo, "MongoClient", Falso)
    loader.conectar("mongodb://localhost:27017/")
    assert "tlsCAFile" not in capturado
    loader.conectar("mongodb+srv://u:p@h/")
    assert "tlsCAFile" in capturado
