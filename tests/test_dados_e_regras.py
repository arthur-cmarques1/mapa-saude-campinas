# -*- coding: utf-8 -*-
"""Integridade de data/ e regras do tratamento. Sem rede."""

import copy
import json
from pathlib import Path

import pytest

import indicadores
import pipeline

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"


def ler(nome):
    return json.loads((DATA / nome).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def estab():
    return ler("estabelecimentos.json")


@pytest.fixture(scope="module")
def regioes():
    return ler("regioes.json")


@pytest.fixture(scope="module")
def referencia():
    return ler("referencia/sms_campinas.json")


@pytest.fixture(scope="module")
def bruto():
    return ler("brutos/cnes_recorte.json")


# ─── Referência oficial ──────────────────────────────────────────────
def test_populacao_fecha_com_o_censo(regioes, referencia):
    assert sum(r["populacao"] for r in regioes) == 1139047
    assert sum(u["populacao_ibge"] for u in referencia["unidades"]) == 1139047


def test_cada_distrito_fecha_com_o_total_publicado(referencia):
    for distrito, total in referencia["populacao_distrito"].items():
        assert sum(u["populacao_ibge"] for u in referencia["unidades"] if u["distrito"] == distrito) == total


def test_seis_distritos_com_o_suleste(regioes):
    assert {r["regiao"] for r in regioes} == {"LESTE", "NOROESTE", "NORTE", "SUDOESTE", "SUL", "SULESTE"}


# ─── Dados tratados ──────────────────────────────────────────────────
def test_contagens_batem_com_o_plano_municipal(estab):
    sus = [e for e in estab if e["vinculo_sus"]]
    assert sum(e["tipo"]["categoria"] == "UBS" for e in sus) == 69
    assert sum(e["tipo"]["categoria"] == "UPA" for e in sus) == 4


def test_nao_ha_unidade_desabilitada(estab, bruto):
    desabilitadas = {str(r["codigo_cnes"]) for r in bruto["registros"]
                     if r["codigo_motivo_desabilitacao_estabelecimento"]}
    assert desabilitadas
    assert not desabilitadas & {e["_id"] for e in estab}


@pytest.mark.parametrize("trecho", ["PENITENCIARIA", "DETENCAO", "COVID", "CAMPANHA"])
def test_nao_ha_unidade_indevida(estab, trecho):
    assert not [e["nome"] for e in estab if trecho in e["nome"].upper()]


def test_cnes_unicos_e_coerentes_com_relacoes(estab):
    ids = [e["_id"] for e in estab]
    assert len(ids) == len(set(ids))
    assert {r["codigo_cnes"] for r in ler("relacoes.json")} == set(ids)


def _dentro(lon, lat, anel):
    dentro = False
    j = len(anel) - 1
    for i in range(len(anel)):
        xi, yi = anel[i][:2]
        xj, yj = anel[j][:2]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def test_todas_as_unidades_ficam_dentro_do_municipio(estab):
    geometria = ler("referencia/limite_campinas.geojson")["features"][0]["geometry"]
    aneis = geometria["coordinates"] if geometria["type"] == "Polygon" else [p[0] for p in geometria["coordinates"]]
    fora = [e["nome"] for e in estab if not any(_dentro(*e["localizacao"]["coordinates"], a) for a in aneis)]
    assert fora == []


def test_hospitais_de_barao_geraldo_nao_ficam_no_centro(estab):
    por_id = {e["_id"]: e for e in estab}
    for cnes in ("2079798", "2081482"):
        lon, lat = por_id[cnes]["localizacao"]["coordinates"]
        assert pipeline.distancia_km(lat, lon, -22.906, -47.064) > 5
        assert por_id[cnes]["endereco"]["regiao"] == "NORTE"


def test_dados_salvos_sao_o_que_o_pipeline_gera(estab, regioes, referencia, bruto):
    documentos = pipeline.tratar(bruto, referencia, ler("referencia/correcoes_coordenadas.json"))
    assert documentos["estabelecimentos"] == estab
    assert documentos["regioes"] == regioes


def test_recorte_nao_guarda_email_nem_cnpj(bruto):
    campos = set(bruto["registros"][0])
    assert not {c for c in campos if "email" in c or "cnpj" in c}


# ─── Regras de tratamento ────────────────────────────────────────────
def _registro(cnes, tipo=2, desab=None, sus="SIM", lat=-22.9, lon=-47.0, bairro="CENTRO"):
    return {
        "codigo_cnes": cnes, "nome_fantasia": f"UNIDADE {cnes}", "nome_razao_social": None,
        "codigo_tipo_unidade": tipo, "codigo_cep_estabelecimento": "13000000",
        "endereco_estabelecimento": "RUA A", "numero_estabelecimento": "1",
        "bairro_estabelecimento": bairro, "numero_telefone_estabelecimento": "(19) 3232-2184",
        "latitude_estabelecimento_decimo_grau": lat, "longitude_estabelecimento_decimo_grau": lon,
        "descricao_turno_atendimento": "X", "estabelecimento_faz_atendimento_ambulatorial_sus": sus,
        "descricao_natureza_juridica_estabelecimento": "1120",
        "codigo_motivo_desabilitacao_estabelecimento": desab, "data_atualizacao": "2026-01-01",
    }


REF = {
    "populacao_distrito": {"LESTE": 1000},
    "servicos_por_distrito": {"20": "LESTE"},
    "unidades": [{"cnes": "1", "distrito": "LESTE", "populacao_ibge": 1000, "populacao_cadastrada": 700, "esf": 2}],
}


def _tratar(*registros):
    return pipeline.tratar({"coletado_em": "2026-01-01", "registros": list(registros)}, copy.deepcopy(REF))


def test_exclui_desabilitada_e_registra_o_motivo():
    docs = _tratar(_registro(1), _registro(9, tipo=5, desab="10"))
    assert [e["_id"] for e in docs["estabelecimentos"]] == ["1"]
    assert docs["excluidos"][0]["motivo"] == "desabilitada no CNES"


def test_ubs_fora_da_lista_oficial_sai_mesmo_com_sus():
    docs = _tratar(_registro(1), _registro(9, tipo=1, sus="SIM"))
    assert [e["_id"] for e in docs["estabelecimentos"]] == ["1"]
    assert "lista oficial" in docs["excluidos"][0]["motivo"]


def test_pronto_atendimento_sem_sus_sai():
    docs = _tratar(_registro(1), _registro(9, tipo=73, sus="NAO"))
    assert docs["excluidos"][0]["motivo"] == "pronto atendimento sem vínculo SUS"


def test_duplicata_de_cnes_conta_uma_vez():
    assert len(_tratar(_registro(1), _registro(1))["estabelecimentos"]) == 1


def test_bairro_vazio_nao_define_distrito():
    """O pipeline antigo mandava bairro vazio para o NORTE; agora o bairro não decide nada."""
    docs = _tratar(_registro(1, bairro=""))
    assert docs["estabelecimentos"][0]["endereco"]["regiao"] == "LESTE"
    assert docs["estabelecimentos"][0]["endereco"]["regiao_origem"] == "tabela oficial de UBS"


def test_origem_do_distrito_fica_registrada():
    docs = _tratar(_registro(1), _registro(20, tipo=5), _registro(21, tipo=5))
    origem = {e["_id"]: e["endereco"]["regiao_origem"] for e in docs["estabelecimentos"]}
    assert origem["20"] == "serviços do distrito no plano municipal"
    assert origem["21"] == "UBS mais próxima"


def test_ubs_oficial_ausente_interrompe_em_vez_de_gerar_numero_errado():
    with pytest.raises(ValueError, match="UBS oficiais"):
        _tratar(_registro(5, tipo=5))


def test_correcao_de_coordenada_nao_altera_o_recorte_original():
    registro = _registro(1)
    correcao = {"1": {"lat": -22.8, "lon": -47.1, "motivo": "", "fonte": ""}}
    docs = pipeline.tratar({"coletado_em": "x", "registros": [registro]}, copy.deepcopy(REF), correcao)
    assert docs["estabelecimentos"][0]["localizacao"]["coordinates"] == [-47.1, -22.8]
    assert registro["latitude_estabelecimento_decimo_grau"] == -22.9


@pytest.mark.parametrize("codigo,esperado", [
    ("1120", "Pública"), ("2062", "Privada"), ("3999", "Sem fins lucrativos"), (None, "Não informada"),
])
def test_natureza_juridica(codigo, esperado):
    assert pipeline._natureza(codigo) == esperado


def test_carga_exige_confirmacao():
    with pytest.raises(RuntimeError, match="confirmar"):
        pipeline.carregar_no_atlas({}, {}, "mongodb://x")


# ─── Coleta e carga, sem rede ────────────────────────────────────────
def test_coleta_pagina_e_descarta_email(monkeypatch):
    chamadas = []

    def falso(url, params=None):
        chamadas.append(params)
        if params["codigo_tipo_unidade"] == 2 and params["offset"] == 0:
            return {"estabelecimentos": [{**_registro(i), "endereco_email_estabelecimento": "x@y"} for i in range(1, 21)]}
        if params["codigo_tipo_unidade"] == 2 and params["offset"] == 20:
            return {"estabelecimentos": [_registro(21)]}
        return {"estabelecimentos": []}

    monkeypatch.setattr(pipeline, "_get_json", falso)
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    bruto = pipeline.coletar_cnes()
    assert len(bruto["registros"]) == 21
    assert "endereco_email_estabelecimento" not in bruto["registros"][0]
    assert sum(c["codigo_tipo_unidade"] == 2 for c in chamadas) == 2


def test_coleta_vazia_nao_apaga_os_dados(monkeypatch):
    monkeypatch.setattr(pipeline, "_get_json", lambda *a, **k: {"estabelecimentos": []})
    with pytest.raises(RuntimeError, match="não foi alterado"):
        pipeline.coletar_cnes()


def test_get_json_tenta_de_novo_e_depois_explica(monkeypatch):
    requests = pytest.importorskip("requests")
    tentativas = []

    def falha(*a, **k):
        tentativas.append(1)
        raise requests.ConnectionError("fora do ar")

    monkeypatch.setattr(requests, "get", falha)
    monkeypatch.setattr(pipeline.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="Falha ao consultar"):
        pipeline._get_json("https://exemplo.invalid", tentativas=3)
    assert len(tentativas) == 3


def test_carga_e_leitura_de_ponta_a_ponta(monkeypatch, estab, regioes, referencia, bruto):
    mongomock = pytest.importorskip("mongomock")
    pytest.importorskip("pymongo")
    import loader

    cliente = mongomock.MongoClient()
    cliente.close = lambda: None
    monkeypatch.setattr(loader, "conectar", lambda uri: cliente)
    documentos = pipeline.tratar(bruto, referencia, ler("referencia/correcoes_coordenadas.json"))
    metadados = pipeline.montar_metadados(bruto, documentos, referencia)

    banco = cliente[loader.NOME_BANCO]
    banco["regioes"].insert_one({"_id": "ANTIGO"})
    contagem = pipeline.carregar_no_atlas(documentos, metadados, "mongodb://x", confirmar_sobrescrita=True)

    assert contagem == {"regioes": 6, "estabelecimentos": 99, "relacoes": 99, "metadados": 1}
    assert banco["regioes"].find_one({"_id": "ANTIGO"}) is None
    assert not [n for n in banco.list_collection_names() if n.endswith("__novo")]
    lidos = loader._ler_docs_atlas("mongodb://x")
    assert len(lidos["estabelecimentos"]) == 99
    assert loader.montar_df_indic(lidos["regioes"]).iloc[0]["regiao"] == "SUDOESTE"


def test_falha_na_carga_preserva_os_dados_atuais(monkeypatch, referencia, bruto):
    mongomock = pytest.importorskip("mongomock")
    pytest.importorskip("pymongo")
    import loader

    cliente = mongomock.MongoClient()
    cliente.close = lambda: None
    monkeypatch.setattr(loader, "conectar", lambda uri: cliente)
    banco = cliente[loader.NOME_BANCO]
    banco["estabelecimentos"].insert_one({"_id": "ATUAL"})
    documentos = pipeline.tratar(bruto, referencia, ler("referencia/correcoes_coordenadas.json"))
    documentos["relacoes"] = []  # insert_many recusa lista vazia: falha no meio da carga
    with pytest.raises(Exception):
        pipeline.carregar_no_atlas(documentos, {"_id": "painel"}, "mongodb://x", confirmar_sobrescrita=True)
    assert banco["estabelecimentos"].find_one({"_id": "ATUAL"})


# ─── Indicadores ─────────────────────────────────────────────────────
@pytest.mark.parametrize("valor,esperado", [
    (100, "Dentro do parâmetro"), (101, "Atenção"), (115, "Atenção"),
    (116, "Sobrecarga"), (130, "Sobrecarga"), (131, "Crítico"),
])
def test_cortes_de_nivel(valor, esperado):
    assert indicadores.nivel(valor) == esperado


def test_pressao_100_e_o_limite_da_pnab():
    assert indicadores.pressao(3500) == 100
    assert indicadores.pressao(1750) == 50


def test_razao_sem_denominador_nao_quebra():
    assert indicadores.razao(100, 0) is None


def test_unidade_sem_cadastro_nao_distorce_a_razao():
    unidades = [
        {"populacao_cadastrada": 7000, "esf": 2},
        {"populacao_cadastrada": None, "esf": 2},
    ]
    r = indicadores.indicadores_distrito(unidades, 20000)
    assert r["cadastrados_por_equipe"] == 3500   # 7000 / 2, não 7000 / 4
    assert r["hab_por_equipe"] == 5000           # 20000 / 4 equipes
    assert r["hab_por_ubs"] == 10000


def test_distrito_sem_cadastro_nao_quebra():
    r = indicadores.indicadores_distrito([{"populacao_cadastrada": None, "esf": 2}], 1000)
    assert r["pressao"] is None and r["nivel"] is None
