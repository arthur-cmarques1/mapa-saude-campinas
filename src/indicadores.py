# -*- coding: utf-8 -*-
"""Regras dos indicadores por distrito de saúde (sem rede, sem pandas).

Parâmetro oficial: a PNAB (Portaria GM/MS 2.436/2017, Anexo, item 3.3) recomenda
de 2.000 a 3.500 pessoas por equipe e 4 equipes por UBS. Ela não fixa um número
de habitantes por UBS; os 14.000 abaixo são derivados (4 x 3.500), não citados.

Os níveis de pressão são uma escolha deste projeto, para leitura leiga. Não são
uma classificação oficial.
"""

LIMITE_POR_EQUIPE = 3500
MINIMO_POR_EQUIPE = 2000
EQUIPES_POR_UBS = 4
REFERENCIA_POR_UBS = LIMITE_POR_EQUIPE * EQUIPES_POR_UBS

# Pressão = pessoas cadastradas por equipe, com 100 igual ao limite da PNAB.
NIVEIS = (
    (100, "Dentro do parâmetro"),
    (115, "Atenção"),
    (130, "Sobrecarga"),
)
NIVEL_MAXIMO = "Crítico"


def pressao(cadastrados_por_equipe):
    """Devolve a pressão em que 100 é o limite recomendado por equipe."""
    if cadastrados_por_equipe is None or cadastrados_por_equipe < 0:
        raise ValueError("cadastrados_por_equipe deve ser um número não negativo")
    return round(cadastrados_por_equipe / LIMITE_POR_EQUIPE * 100)


def nivel(valor_pressao):
    for teto, nome in NIVEIS:
        if valor_pressao <= teto:
            return nome
    return NIVEL_MAXIMO


def razao(numerador, denominador):
    """Divisão arredondada; None quando não há denominador (ex.: distrito sem UBS)."""
    if not denominador:
        return None
    return round(numerador / denominador)


def indicadores_distrito(unidades_oficiais, populacao_distrito):
    """Calcula os indicadores a partir das linhas oficiais de um distrito.

    A população cadastrada e as equipes usadas na razão vêm só de unidades com
    cadastro publicado, para numerador e denominador cobrirem as mesmas unidades.
    """
    com_cadastro = [u for u in unidades_oficiais if u["populacao_cadastrada"] is not None]
    cadastrados = sum(u["populacao_cadastrada"] for u in com_cadastro)
    equipes_com_cadastro = sum(u["esf"] for u in com_cadastro)
    equipes = sum(u["esf"] for u in unidades_oficiais)

    cadastrados_por_equipe = razao(cadastrados, equipes_com_cadastro)
    valor_pressao = None if cadastrados_por_equipe is None else pressao(cadastrados_por_equipe)
    return {
        "equipes": equipes,
        "populacao_cadastrada": cadastrados,
        "hab_por_ubs": razao(populacao_distrito, len(unidades_oficiais)),
        "hab_por_equipe": razao(populacao_distrito, equipes),
        "cadastrados_por_equipe": cadastrados_por_equipe,
        "pressao": valor_pressao,
        "nivel": None if valor_pressao is None else nivel(valor_pressao),
    }
