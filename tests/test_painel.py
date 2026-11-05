# -*- coding: utf-8 -*-
"""Geração do painel: arquivo único, conteúdo correto e segurança do HTML."""

import copy
import importlib
import json
import re
from pathlib import Path

import pytest

import dashboard
import loader

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def sem_mongo(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("DASHBOARD_SAIDA", raising=False)


@pytest.fixture(scope="module")
def documentos():
    docs = loader._ler_docs_locais()
    docs["excluidos"] = json.loads((RAIZ / "data" / "excluidos.json").read_text(encoding="utf-8"))
    return docs


@pytest.fixture(scope="module")
def pagina(documentos):
    return dashboard.renderizar(documentos)


@pytest.fixture(scope="module")
def visivel(pagina):
    sem_codigo = re.sub(r"<(script|style)\b.*?</\1>", " ", pagina, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", sem_codigo))


# ─── Funciona sem internet ───────────────────────────────────────────
def test_nao_carrega_nada_de_fora(pagina):
    assert not re.findall(r"<script[^>]+src=", pagina)
    assert not re.findall(r"<link[^>]+stylesheet", pagina)


def test_fonte_embutida_no_arquivo(pagina):
    assert "@font-face{font-family:Figtree" in pagina
    assert "url(data:font/woff2;base64," in pagina
    assert "font-src data:" in pagina


def test_sem_placeholder_esquecido(visivel):
    assert not re.search(r"\$[a-z_]+", visivel)
    assert "None" not in visivel and "nan" not in visivel.split()


def test_docs_index_esta_atualizado(pagina):
    assert (RAIZ / "docs" / "index.html").read_text(encoding="utf-8") == pagina


def test_geracao_e_deterministica(documentos, pagina):
    assert dashboard.renderizar(documentos) == pagina


# ─── Conteúdo ────────────────────────────────────────────────────────
@pytest.mark.parametrize("frase_antiga", [
    "1 UBS para cada", "7 em cada 10", "vezes acima", "dados oficiais e atualizados", "penitenciárias",
])
def test_afirmacoes_sem_base_nao_voltam(visivel, frase_antiga):
    assert frase_antiga not in visivel


def test_numeros_no_formato_brasileiro(visivel):
    assert "1.139.047" in visivel
    assert not re.search(r"\b\d{1,3},\d{3}\b", visivel)


def test_parametro_e_fonte_aparecem(visivel, pagina):
    assert "2.000 a 3.500" in visivel
    assert "prt2436_22_09_2017" in pagina


def test_todos_os_distritos_e_unidades_aparecem(pagina, documentos):
    sus = [e for e in documentos["estabelecimentos"] if e["vinculo_sus"]]
    assert pagina.count('class="unidade"') == len(sus) == 84
    for distrito in ("Leste", "Noroeste", "Norte", "Sudoeste", "Sul", "Sudeste"):
        assert f"></i>{distrito}</th>" in pagina


def test_nome_do_distrito_e_sudeste_em_todo_o_painel(pagina):
    assert "suleste" not in pagina.lower()
    assert 'value="SUDESTE"' in pagina


def test_plotly_fica_guardado_como_texto(pagina):
    assert '<script id="js-plotly" type="text/plain">' in pagina


def test_aviso_de_emergencia_vem_antes_do_conteudo(pagina):
    assert pagina.index('href="tel:192"') < pagina.index('id="conteudo"')


def test_csv_abre_no_excel_em_portugues():
    uri = dashboard.csv_data_uri([["São José", 1]], ["nome", "n"])
    assert uri.startswith("data:text/csv;charset=utf-8,%EF%BB%BF")
    assert "%3B" in uri  # separador ponto e vírgula


# ─── Segurança ───────────────────────────────────────────────────────
def test_nome_malicioso_e_neutralizado(documentos):
    docs = copy.deepcopy(documentos)
    ataque = "</script><script>alert(1)</script><img src=x onerror=alert(1)>"
    for unidade in docs["estabelecimentos"]:
        if unidade["vinculo_sus"]:
            unidade["nome"] = ataque
            unidade["endereco"]["logradouro"] = ataque
            break
    pagina = dashboard.renderizar(docs)
    assert "<script>alert(1)" not in pagina
    assert "<img src=x" not in pagina.lower()


def test_json_embutido_nao_fecha_o_script():
    texto = dashboard.json_para_script({"a": "</script><b>"})
    assert "</script" not in texto
    assert json.loads(texto) == {"a": "</script><b>"}


def test_politica_de_seguranca_presente(pagina):
    assert "Content-Security-Policy" in pagina


# ─── Acessibilidade estrutural ───────────────────────────────────────
def test_estrutura_acessivel(pagina):
    assert '<html lang="pt-BR"' in pagina
    assert 'class="pular"' in pagina and "<main" in pagina
    assert pagina.count("<h1") == 1
    assert pagina.count('scope="col"') == 11


def test_campos_tem_rotulo(pagina):
    for campo in ("busca", "filtro-cat", "filtro-regiao"):
        assert f'<label for="{campo}"' in pagina


# ─── Formatação ──────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada,saida", [
    ("CENTRO DE SAUDE SAO JOSE", "Centro de Saúde São José"),
    ("CENTRO DE SAUDE DIC III", "Centro de Saúde DIC III"),
    ("HOSPITAL DAS CLINICAS DA UNICAMP", "Hospital das Clínicas da UNICAMP"),
    ("E ALGO", "E Algo"),
])
def test_nome_legivel(entrada, saida):
    assert dashboard.nome_legivel(entrada) == saida


@pytest.mark.parametrize("entrada,saida", [
    ("(19) 3232-2184", "tel:+551932322184"),
    ("3232-2184", "tel:+551932322184"),
    ("(19) 99999-0000", "tel:+5519999990000"),
    ("", None),
    ("123", None),
])
def test_link_telefone(entrada, saida):
    assert dashboard.link_telefone(entrada) == saida


# ─── Comportamento do módulo ─────────────────────────────────────────
def test_importar_nao_grava_arquivo(tmp_path, monkeypatch):
    destino = tmp_path / "x.html"
    monkeypatch.setenv("DASHBOARD_SAIDA", str(destino))
    importlib.reload(dashboard)
    assert not destino.exists()


def test_gerar_respeita_a_saida(tmp_path, monkeypatch):
    destino = tmp_path / "sub" / "painel.html"
    monkeypatch.setenv("DASHBOARD_SAIDA", str(destino))
    assert dashboard.gerar() == destino
    assert destino.stat().st_size > 1_000_000
    assert not list(destino.parent.glob("*.tmp"))


def test_grafo_tem_uma_aresta_por_unidade(documentos):
    _, df_indic, df_sus, _ = dashboard.preparar(documentos)
    grafo = dashboard.montar_grafo(df_indic, df_sus)
    assert grafo.number_of_edges() == len(df_sus)
    assert grafo.number_of_nodes() == len(df_sus) + len(df_indic)


def test_rotulos_de_distrito_nao_se_sobrepoem(documentos):
    _, df_indic, df_sus, _ = dashboard.preparar(documentos)
    grafo = dashboard.montar_grafo(df_indic, df_sus)
    pos = dashboard.posicoes_grafo(grafo)
    centros = [pos[n] for n, d in grafo.nodes(data=True) if d["tipo"] == "regiao"]
    menor = min(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                for i, a in enumerate(centros) for b in centros[i + 1:])
    assert menor > 0.9


def test_posicoes_do_grafo_nao_dependem_do_sistema(documentos):
    _, df_indic, df_sus, _ = dashboard.preparar(documentos)
    pos = dashboard.posicoes_grafo(dashboard.montar_grafo(df_indic, df_sus))
    assert all(round(v, 6) == v for ponto in pos.values() for v in ponto)


def test_mapa_nao_usa_servidor_que_bloqueia_arquivo_local(pagina):
    """O OSM exige Referer e devolve uma imagem de bloqueio com status 200 a quem abre por file://."""
    assert "tile.openstreetmap.org" not in pagina
    assert "img-src data: https://server.arcgisonline.com" in pagina
    assert "Canvas/World_Light_Gray_Base" in pagina and "World_Street_Map" in pagina


def test_nome_do_distrito_nao_fica_sobre_uma_unidade(documentos):
    _, df_indic, df_sus, _ = dashboard.preparar(documentos)
    grafo = dashboard.montar_grafo(df_indic, df_sus)
    pos = dashboard.posicoes_grafo(grafo)
    for no, dados in grafo.nodes(data=True):
        if dados["tipo"] != "regiao":
            continue
        rx, ry = pos[no][0] * dashboard.FATOR_ROTULO_GRAFO, pos[no][1] * dashboard.FATOR_ROTULO_GRAFO
        folga = min(((pos[v][0] - rx) ** 2 + (pos[v][1] - ry) ** 2) ** 0.5 for v in grafo.neighbors(no))
        assert folga > 0.12, no


def test_composicao_dos_hospitais_soma_o_total(documentos):
    _, df_indic, df_sus, metadados = dashboard.preparar(documentos)
    texto = dashboard.conclusoes(df_indic, None, df_sus, metadados)
    trecho = re.search(r"o cadastro indica ([^.]+)\.", texto).group(1)
    assert sum(int(n) for n in re.findall(r"\b\d+\b", trecho)) == 11
    assert "1 privado" in trecho and "1 privados" not in trecho


def test_aviso_quando_cadastro_supera_o_censo(documentos):
    _, df_indic, _, _ = dashboard.preparar(documentos)
    assert "Sudoeste" in dashboard.aviso_cadastro(df_indic)
    df = df_indic.copy()
    df["populacao_cadastrada"] = 0
    assert dashboard.aviso_cadastro(df) == ""
