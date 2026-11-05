# -*- coding: utf-8 -*-
"""Abre docs/index.html em um Chromium real, sem internet e como arquivo local."""

import re
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.navegador
PAINEL = (Path(__file__).resolve().parent.parent / "docs" / "index.html").as_uri()
GRAFICOS = ["g-pressao", "g-hab-ubs", "g-medidas", "g-hospitais", "g-composicao", "g-grafo"]
CENTRO_CAMPINAS = {"latitude": -22.9028, "longitude": -47.0556}


@pytest.fixture(scope="module")
def navegador():
    with sync_api.sync_playwright() as p:
        try:
            nav = p.chromium.launch()
        except sync_api.Error as erro:
            pytest.skip(f"Chromium indisponível: {erro}")
        yield nav
        nav.close()


@pytest.fixture
def abrir(navegador):
    contextos = []

    def _abrir(largura=1280, altura=900, offline=True, **opcoes):
        contexto = navegador.new_context(viewport={"width": largura, "height": altura}, **opcoes)
        contextos.append(contexto)
        if offline:
            contexto.route(re.compile(r"^https?://"), lambda rota: rota.abort())
        pagina = contexto.new_page()
        pagina.erros = []
        pagina.on("pageerror", lambda erro: pagina.erros.append(str(erro)))
        pagina.goto(PAINEL)
        pagina.wait_for_function("window.__painelPronto === true")
        return pagina

    yield _abrir
    for contexto in contextos:
        contexto.close()


def visiveis(pagina):
    return pagina.locator(".unidade:visible")


def test_abre_sem_internet_e_sem_erros(abrir):
    pagina = abrir()
    for grafico in GRAFICOS:
        pagina.wait_for_selector(f"#{grafico} .main-svg", state="attached")
    assert pagina.locator(".leaflet-interactive").count() >= 84
    assert pagina.erros == []


def test_sem_internet_avisa_e_mantem_as_unidades(abrir):
    pagina = abrir()
    sync_api.expect(pagina.locator("#aviso-mapa")).to_contain_text("Sem conexão", timeout=15000)
    assert pagina.locator("path.leaflet-interactive").count() >= 84


def test_busca_ignora_acentos_e_maiusculas(abrir):
    pagina = abrir()
    pagina.fill("#busca", "barao geraldo")
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("encontrada")
    assert "Barão Geraldo" in visiveis(pagina).first.inner_text()
    pagina.fill("#busca", "BARÃO GERALDO")
    assert "Barão Geraldo" in visiveis(pagina).first.inner_text()


def test_busca_sem_resultado_explica(abrir):
    pagina = abrir()
    pagina.fill("#busca", "xyzxyz")
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("Nenhuma unidade")
    assert visiveis(pagina).count() == 0


def test_filtros_combinados(abrir):
    pagina = abrir()
    pagina.select_option("#filtro-cat", "UPA")
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("4 unidades")
    pagina.select_option("#filtro-regiao", "NOROESTE")
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("1 unidade encontrada")


def test_filtro_tambem_atualiza_o_mapa(abrir):
    pagina = abrir()
    pagina.select_option("#filtro-cat", "UPA")
    sync_api.expect(pagina.locator("path.leaflet-interactive")).to_have_count(4)


def test_mostrar_mais_pagina_a_lista(abrir):
    pagina = abrir()
    assert visiveis(pagina).count() == 12
    pagina.click("#mostrar-mais")
    assert visiveis(pagina).count() == 24


def test_localizacao_ordena_pela_mais_proxima(abrir):
    pagina = abrir(geolocation=CENTRO_CAMPINAS, permissions=["geolocation"])
    pagina.click("#usar-local")
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("da mais perto")
    distancias = visiveis(pagina).locator(".distancia").all_inner_texts()
    assert all(distancias)
    assert "Centro" in visiveis(pagina).first.inner_text()


def test_localizacao_negada_nao_trava(abrir):
    pagina = abrir()
    pagina.evaluate("() => { navigator.geolocation.getCurrentPosition = (ok, falha) => falha({code: 1}); }")
    pagina.click("#usar-local")
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("Não foi possível")
    pagina.fill("#busca", "centro")
    assert visiveis(pagina).count() > 0


def test_clique_no_mapa_define_o_ponto(abrir):
    pagina = abrir()
    # Canto inferior esquerdo: fora dos controles de zoom e das unidades.
    caixa = pagina.locator("#mapa").bounding_box()
    pagina.locator("#mapa").click(position={"x": 12, "y": caixa["height"] - 12})
    sync_api.expect(pagina.locator("#status-busca")).to_contain_text("da mais perto")


def test_ver_no_mapa_abre_o_popup(abrir):
    pagina = abrir()
    visiveis(pagina).first.locator(".ver-no-mapa").click()
    sync_api.expect(pagina.locator(".leaflet-popup-content")).to_be_visible()


def test_tema_alterna_e_e_lembrado(abrir):
    pagina = abrir(color_scheme="dark")
    assert pagina.evaluate("document.documentElement.dataset.tema") == "escuro"
    pagina.click("#alternar-tema")
    assert pagina.evaluate("document.documentElement.dataset.tema") == "claro"
    pagina.reload()
    assert pagina.evaluate("document.documentElement.dataset.tema") == "claro"


def test_respeita_preferencia_do_sistema(abrir):
    assert abrir(color_scheme="light").evaluate("document.documentElement.dataset.tema") == "claro"


@pytest.mark.parametrize("largura", [320, 390, 768, 1280])
def test_nao_ha_rolagem_horizontal(abrir, largura):
    pagina = abrir(largura=largura)
    excesso = pagina.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert excesso <= 0


def test_sem_javascript_o_conteudo_continua_disponivel(navegador):
    contexto = navegador.new_context(java_script_enabled=False)
    pagina = contexto.new_page()
    pagina.goto(PAINEL)
    assert pagina.locator(".unidade:visible").count() == 84
    assert pagina.locator("tbody tr").count() == 6
    assert pagina.locator("#mapa").is_hidden()
    assert "precisam de JavaScript" in pagina.content()
    contexto.close()


def test_primeira_tecla_tab_chega_no_atalho_de_pular(abrir):
    pagina = abrir()
    pagina.keyboard.press("Tab")
    assert pagina.evaluate("document.activeElement.className") == "pular"
