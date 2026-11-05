# -*- coding: utf-8 -*-
"""Extrai do Plano Municipal de Saúde 2026-2029 a referência oficial dos distritos.

Gera data/referencia/sms_campinas.json. O arquivo gerado é versionado, então
só é preciso rodar isto quando sair um plano novo (requer: pip install pymupdf).

    python scripts/extrair_referencia_sms.py caminho/para/PMS_2026-2029.pdf
"""

import json
import re
import sys
from pathlib import Path

import pymupdf

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "data" / "referencia" / "sms_campinas.json"

URL_PMS = (
    "https://portal-adm.campinas.sp.gov.br/sites/default/files/secretarias/"
    "arquivos-avulsos/125/2026/05/07-104042/PMS_2026-2029_Campinas_Matriz_Geral.pdf"
)

# Páginas do PDF (a numeração impressa é a do PDF + 2).
PAGINAS_TABELA = (96, 97, 98)

# Totais publicados no texto de cada distrito; servem de conferência da extração.
POPULACAO_DISTRITO = {
    "LESTE": 213642,
    "NOROESTE": 173591,
    "NORTE": 197596,
    "SUDESTE": 185853,
    "SUDOESTE": 183424,
    "SUL": 184941,
}
POPULACAO_MUNICIPIO = 1139047

# O plano grafa este distrito como "Suleste"; o projeto usa "Sudeste".
GRAFIA_DO_PLANO = {"SULESTE": "SUDESTE"}

# A tabela geral omite esta unidade; ela consta na tabela do Distrito Leste
# (população e eSF), sem população cadastrada. Com ela, o distrito fecha o total.
UNIDADES_FORA_DA_TABELA = [
    {
        "cnes": "6028179",
        "distrito": "LESTE",
        "populacao_ibge": 14936,
        "populacao_cadastrada": None,
        "esf": 2,
    }
]

# Serviços citados nas seções de cada distrito (CNES do cadastro nacional).
SERVICOS_POR_DISTRITO = {
    "2022648": "LESTE",     # Irmandade de Misericórdia de Campinas (Santa Casa)
    "2078465": "LESTE",     # Real Sociedade Portuguesa de Beneficência
    "2022621": "LESTE",     # Maternidade de Campinas
    "5874998": "NOROESTE",  # UPA Dr. Sérgio Arouca (Campo Grande)
    "2082128": "NOROESTE",  # Hospital e Maternidade Celso Pierro
    "4098110": "NORTE",     # UPA Anchieta Metropolitano
    "6053858": "SUDOESTE",  # Complexo Hospitalar Prefeito Edivaldo Orsi
    "2023571": "SUL",       # UPA São José
    "9912266": "SUDESTE",   # UPA Carlos Lourenço
    "2081490": "SUDESTE",   # Hospital Municipal Dr. Mário Gatti
}


def _inteiro(texto):
    return int(re.sub(r"\D", "", texto))


def extrair_tabela(caminho_pdf):
    doc = pymupdf.open(caminho_pdf)
    unidades, distrito = [], None
    for numero in PAGINAS_TABELA:
        for tabela in doc[numero - 1].find_tables().tables:
            for linha in tabela.extract():
                celulas = [(c or "").replace("\n", " ").strip() for c in linha]
                if len(celulas) < 6 or not re.fullmatch(r"\d{6,7}", celulas[1]):
                    continue
                if celulas[0].startswith("Distrito"):
                    nome = celulas[0].split()[1].upper()
                    distrito = GRAFIA_DO_PLANO.get(nome, nome)
                unidades.append({
                    "cnes": celulas[1],
                    "distrito": distrito,
                    "populacao_ibge": _inteiro(celulas[3]),
                    "populacao_cadastrada": _inteiro(celulas[4]),
                    "esf": _inteiro(celulas[5]),
                })
    return unidades


def conferir(unidades):
    """Interrompe se a extração não fechar com os totais publicados no plano."""
    for distrito, esperado in POPULACAO_DISTRITO.items():
        soma = sum(u["populacao_ibge"] for u in unidades if u["distrito"] == distrito)
        if soma != esperado:
            raise SystemExit(f"{distrito}: soma {soma} difere do publicado {esperado}")
    total = sum(u["populacao_ibge"] for u in unidades)
    if total != POPULACAO_MUNICIPIO:
        raise SystemExit(f"Total {total} difere do Censo {POPULACAO_MUNICIPIO}")


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    unidades = extrair_tabela(sys.argv[1]) + UNIDADES_FORA_DA_TABELA
    conferir(unidades)
    referencia = {
        "fonte": {
            "documento": "Plano Municipal de Saúde de Campinas 2026-2029",
            "url": URL_PMS,
            "paginas_impressas": "98 a 100 (unidades); 78 a 91 (distritos e serviços)",
            "referencia_populacao": "IBGE, Censo 2022",
            "referencia_cadastro": "população cadastrada em dez/2024; equipes em nov/2024",
        },
        "dependencia_sus": {"percentual": 60, "pessoas": 683428},
        "populacao_municipio": POPULACAO_MUNICIPIO,
        "populacao_distrito": POPULACAO_DISTRITO,
        "servicos_por_distrito": SERVICOS_POR_DISTRITO,
        "unidades": sorted(unidades, key=lambda u: (u["distrito"], int(u["cnes"]))),
    }
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(referencia, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(unidades)} unidades conferidas e gravadas em {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
