# -*- coding: utf-8 -*-
# =====================================================================
# REGISTRO HISTÓRICO (etapas 1 a 4)
#
# Este arquivo preserva o código que o grupo usou para coletar, tratar e
# carregar os dados. Ele NÃO faz parte do fluxo reproduzível do
# repositório: o fluxo atual parte dos JSONs em data/ (ver loader.py).
#
# Notas de reorganização (o restante do arquivo é o código original):
#   - O texto abaixo cita uma "ETAPA 5" e um bloco "if __name__" que não
#     existem neste arquivo. A leitura dos dados agora está em loader.py.
#   - Nenhuma função é chamada ao importar este módulo.
#   - A etapa 4 apaga (drop) coleções no Atlas; ver o parâmetro
#     confirmar_sobrescrita em etapa_4_carregar_no_atlas.
#   - Refazer a coleta pode gerar números diferentes (CNES e IBGE mudam).
# =====================================================================

"""
=====================================================================
 PIPELINE COMPLETO — Projeto Integrador "Mapa de Acesso à Saúde
 Pública em Campinas"
 PUC-Campinas — Bancos de Dados Não Relacionais — 2026

 Grupo: Arthur Costa Marques, Conrado Marques,
        Fábio Barbosa Gonsalez, Patrick Rovaron Franco
 Docente: Joice Marin
=====================================================================

 Este arquivo documenta todo o caminho percorrido pelo grupo, da
 coleta nas fontes públicas até a carga no MongoDB Atlas. Está
 organizado em 5 ETAPAS sequenciais, cada uma claramente identificada.

 ┌─────────────────────────────────────────────────────────────────┐
 │  ATENÇÃO — STATUS DAS ETAPAS                                    │
 │                                                                 │
 │  ETAPA 1 (Coleta CNES + IBGE)    → JÁ EXECUTADA (não rodar)    │
 │  ETAPA 2 (Tratamento)             → JÁ EXECUTADA (não rodar)    │
 │  ETAPA 3 (Exportação CSV → JSON)  → JÁ EXECUTADA (não rodar)    │
 │  ETAPA 4 (Carga no MongoDB Atlas) → JÁ EXECUTADA (não rodar)    │
 │  ETAPA 5 (Leitura do Atlas)       → EXECUTAR a cada sessão      │
 │                                                                 │
 │  As etapas 1-4 ficam no arquivo como REGISTRO do que foi feito. │
 │  Para reproduzir o pipeline do zero, basta descomentar a chamada│
 │  de cada função no bloco "if __name__" no final do arquivo.     │
 └─────────────────────────────────────────────────────────────────┘
"""

import time
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import requests


# =====================================================================
#  CONFIGURAÇÃO GLOBAL
# =====================================================================

DATA_DIR = Path("dados")
DATA_DIR.mkdir(exist_ok=True)

# Códigos do município de Campinas
COD_CAMPINAS = "350950"        # 6 dígitos (usado no CNES)
COD_CAMPINAS_7 = "3509502"     # 7 dígitos (usado no IBGE/SIDRA)

# Endpoints das APIs públicas
URL_CNES = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
URL_SIDRA = "https://apisidra.ibge.gov.br/values/t/4709/n6/{}/v/93/p/last"

# =====================================================================
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  ETAPA 1 — COLETA DOS DADOS NAS APIs PÚBLICAS                     ║
# ║                                                                   ║
# ║  STATUS: JÁ EXECUTADA — não precisa rodar novamente               ║
# ║                                                                   ║
# ║  O que foi feito:                                                 ║
# ║    • Consultamos a API DEMAS do Ministério da Saúde para baixar   ║
# ║      TODOS os estabelecimentos do município de Campinas (4.925).  ║
# ║    • Consultamos o SIDRA do IBGE para obter a população oficial   ║
# ║      do Censo 2022 (1.139.047 habitantes).                        ║
# ║    • Salvamos os dados brutos em CSV.                             ║
# ╚═══════════════════════════════════════════════════════════════════╝
# =====================================================================

# Dicionário oficial de tipos de estabelecimento do CNES
TIPOS_CNES = {
    1: "POSTO DE SAÚDE",
    2: "CENTRO DE SAÚDE / UNIDADE BÁSICA",
    4: "POLICLÍNICA",
    5: "HOSPITAL GERAL",
    7: "HOSPITAL ESPECIALIZADO",
    15: "UNIDADE MISTA",
    20: "PRONTO SOCORRO GERAL",
    21: "PRONTO SOCORRO ESPECIALIZADO",
    22: "CONSULTÓRIO ISOLADO",
    36: "CLÍNICA / CENTRO DE ESPECIALIDADE",
    39: "UNIDADE DE APOIO DIAGNOSE E TERAPIA",
    73: "PRONTO ATENDIMENTO",
}


def etapa_1_baixar_cnes():
    """
    Pagina pela API do CNES (limite de 20 registros por requisição)
    até trazer todos os estabelecimentos do município.
    Resultado: ~4.925 estabelecimentos brutos.
    """
    print("[ETAPA 1] Baixando estabelecimentos do CNES...")
    todos = []
    offset, limit = 0, 20

    while True:
        r = requests.get(
            URL_CNES,
            params={"codigo_municipio": COD_CAMPINAS,
                    "limit": limit, "offset": offset},
            timeout=120,
        )
        r.raise_for_status()
        lote = r.json().get("estabelecimentos", [])

        if not lote:
            break

        todos.extend(lote)
        if len(todos) % 500 == 0:
            print(f"  {len(todos)} registros...")

        offset += limit
        if len(lote) < limit:
            break
        time.sleep(0.2)

    print(f"  ✓ {len(todos)} estabelecimentos baixados")
    df_raw = pd.DataFrame(todos)
    df_raw.to_csv(DATA_DIR / "cnes_raw.csv", index=False)
    return df_raw


def etapa_1_baixar_populacao():
    """
    Consulta o SIDRA para obter a população oficial de Campinas.
    Resultado: 1.139.047 habitantes (Censo 2022).
    """
    print("\n[ETAPA 1] Baixando população via SIDRA/IBGE...")
    r = requests.get(URL_SIDRA.format(COD_CAMPINAS_7), timeout=60)
    r.raise_for_status()
    pop = int(r.json()[1]["V"])
    print(f"  ✓ Total Campinas (Censo 2022): {pop:,}")
    return pop

# =====================================================================
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  ETAPA 2 — TRATAMENTO E LIMPEZA DOS DADOS                         ║
# ║                                                                   ║
# ║  STATUS: JÁ EXECUTADA — não precisa rodar novamente               ║
# ║                                                                   ║
# ║  O que foi feito:                                                 ║
# ║    1. Normalização das colunas vindas da API.                     ║
# ║    2. Filtragem dos 4.925 registros brutos para reter apenas      ║
# ║       UBS, Hospitais e UPAs (115 estabelecimentos finais).        ║
# ║    3. Mapeamento de bairros para os 5 distritos de saúde da SMS   ║
# ║       (NORTE, SUL, LESTE, SUDOESTE, NOROESTE).                    ║
# ║    4. Validação geográfica das coordenadas (bounding box).        ║
# ║    5. Remoção de duplicatas pelo código CNES.                     ║
# ║    6. Cálculo dos indicadores (habitantes por UBS por distrito).  ║
# ║                                                                   ║
# ║  Resultado salvo em: dados/estabelecimentos_clean.csv             ║
# ║                      dados/indicadores.csv                        ║
# ║                      dados/populacao_distritos.csv                ║
# ╚═══════════════════════════════════════════════════════════════════╝
# =====================================================================

# Mapeamento código CNES → categoria do projeto (foco em 3 tipos)
CATEGORIA = {
    "01": "UBS", "02": "UBS",
    "05": "Hospital", "07": "Hospital", "15": "Hospital",
    "20": "Urgência", "21": "Urgência",
    "73": "UPA",
}
CATEGORIA_FOCO = {k: v for k, v in CATEGORIA.items()
                  if v in ["UBS", "Hospital", "UPA"]}

# Proporções populacionais por distrito de saúde (estimativa SMS)
# O IBGE não publica dados nessa divisão, então usamos proporções
# documentadas que somam o total oficial do Censo 2022.
PROPORCOES_SMS = {
    "NORTE": 0.168, "SUL": 0.190, "LESTE": 0.188,
    "SUDOESTE": 0.301, "NOROESTE": 0.153,
}

# Centróides geográficos aproximados dos 5 distritos de saúde
CENTROIDES = {
    "NORTE":    (-22.840, -47.050),
    "SUL":      (-22.950, -47.070),
    "LESTE":    (-22.900, -47.040),
    "SUDOESTE": (-22.965, -47.130),
    "NOROESTE": (-22.930, -47.145),
}

# Bounding box de Campinas (filtra coordenadas inválidas)
BBOX = {"lat_min": -23.10, "lat_max": -22.65,
        "lon_min": -47.25, "lon_max": -46.85}

# Mapeamento bairro normalizado → distrito de saúde (~100 bairros)
MAPEAMENTO_DISTRITOS = {
    # ─── NORTE ───
    "BARAO GERALDO": "NORTE", "CIDADE UNIVERSITARIA": "NORTE",
    "TAQUARAL": "NORTE", "SOUSAS": "NORTE", "JOAQUIM EGIDIO": "NORTE",
    "JARDIM NOVA EUROPA": "NORTE", "JARDIM EULINA": "NORTE",
    "JARDIM SANTA MONICA": "NORTE", "FAZENDA SANTA CANDIDA": "NORTE",
    "BOSQUE": "NORTE", "JARDIM PROENCA": "NORTE", "GUANABARA": "NORTE",
    "JARDIM GUARANI": "NORTE", "JARDIM SANTA GENEBRA": "NORTE",
    "JARDIM CAMPINEIRO": "NORTE", "NOVA CAMPINAS": "NORTE",
    "PARQUE TAQUARAL": "NORTE", "PARQUE RURAL FAZENDA": "NORTE",
    # ─── SUL ───
    "VILA INDUSTRIAL": "SUL", "JARDIM AURELIA": "SUL",
    "JARDIM CARLOS LOURENCO": "SUL", "PARQUE OZIEL": "SUL",
    "JARDIM SAO MARCOS": "SUL", "JARDIM SANTA ODILA": "SUL",
    "JARDIM CAMPOS ELISEOS": "SUL", "CAMPOS ELISEOS": "SUL",
    "VILA RICA": "SUL", "JARDIM AEROPORTO": "SUL", "PARQUE ITALIA": "SUL",
    "JARDIM FLORENCE": "SUL", "JARDIM FLORENCE II": "SUL",
    "JARDIM MAISA": "SUL", "PARQUE DA FIGUEIRA": "SUL",
    "PARQUE INDUSTRIAL LISBOA": "SUL", "VILA SAO BERNARDO": "SUL",
    "SAO BERNARDO": "SUL", "JARDIM ROSSIN": "SUL",
    "JARDIM IPAUSSURAMA": "SUL", "JARDIM SAO GABRIEL": "SUL",
    "PARQUE SANTA BARBARA": "SUL",
    # ─── LESTE ───
    "CENTRO": "LESTE", "BAIRRO CENTRO": "LESTE", "CAMBUI": "LESTE",
    "BOTAFOGO": "LESTE", "JARDIM SAO JOSE": "LESTE",
    "JARDIM CONCEICAO": "LESTE", "VILA BOA VISTA": "LESTE",
    "JARDIM CAMPO BELO": "LESTE", "VILA BRANDINA": "LESTE",
    "JARDIM SAN DIEGO": "LESTE", "JARDIM SAO VICENTE": "LESTE",
    "JARDIM SAO DOMINGOS": "LESTE", "VILA OROZIMBO MAIA": "LESTE",
    "VILA UNIAO": "LESTE", "VILA ITAPURA": "LESTE",
    "JARDIM SANTA LUCIA": "LESTE", "VILA JOAQUIM INACIO": "LESTE",
    "JARDIM ROSALIA": "LESTE", "VILA JOAO JORGE": "LESTE",
    "JARDIM AFIFE": "LESTE", "PARQUE UNIVERSITARIO": "LESTE",
    "JARDIM SANTA ROSA": "LESTE", "PARQUE VISTA ALEGRE": "LESTE",
    "VILA PROOST DE SOUZA": "LESTE", "JARDIM DAS OLIVEIRAS": "LESTE",
    # ─── SUDOESTE ───
    "CAMPO GRANDE": "SUDOESTE", "DIC I": "SUDOESTE", "DIC II": "SUDOESTE",
    "DIC III": "SUDOESTE", "DIC IV": "SUDOESTE", "DIC V": "SUDOESTE",
    "DIC VI": "SUDOESTE", "JARDIM SAO QUIRINO": "SUDOESTE",
    "SAO QUIRINO": "SUDOESTE", "PARQUE ITAJAI": "SUDOESTE",
    "PARQUE ITAJAI II": "SUDOESTE", "RESIDENCIAL COSMOS": "SUDOESTE",
    "PARQUE VALENCA I": "SUDOESTE", "PARQUE VALENCA": "SUDOESTE",
    "CIDADE SATELITE IRIS": "SUDOESTE", "SATELITE IRIS II": "SUDOESTE",
    "JARDIM BASSOLI": "SUDOESTE", "JARDIM MONTE BELO": "SUDOESTE",
    "VILA CASTELO BRANCO": "SUDOESTE", "JARDIM FERNANDA II": "SUDOESTE",
    "JARDIM FERNANDA": "SUDOESTE", "JARDIM YEDA": "SUDOESTE",
    "JARDIM LISA": "SUDOESTE", "JARDIM NOVA AMERICA": "SUDOESTE",
    "JARDIM ADEMAR DE BARROS": "SUDOESTE", "VILA SAN MARTIN": "SUDOESTE",
    "JARDIM BANDEIRA 2": "SUDOESTE", "PARQUE RESIDENCIAL CARVA": "SUDOESTE",
    "CONJUNTO HABITACIONAL EDIVALDO ANTONIO": "SUDOESTE",
    "CONJUNTO HABITACIONAL PARQ": "SUDOESTE",
    "CHACARA NOVA BOA VISTA": "SUDOESTE", "NOVA BOA VISTA": "SUDOESTE",
    "VILA VITORIA": "SUDOESTE", "VILLAGE": "SUDOESTE",
    "CAMPINA GRANDE": "SUDOESTE", "CAPIVARI": "SUDOESTE",
    # ─── NOROESTE ───
    "VILA PADRE ANCHIETA": "NOROESTE", "VILA PE ANCHIETA": "NOROESTE",
    "VILA PERSEU LEITE DE BARROS": "NOROESTE",
    "JARDIM SATELITE IRIS": "NOROESTE",
}


def normalizar_bairro(texto):
    """
    Limpa nome do bairro: remove acentos, expande abreviações
    comuns no CNES (JD → JARDIM, VL → VILA, PQ → PARQUE), corrige typos.
    """
    if not isinstance(texto, str):
        return ""
    s = unicodedata.normalize("NFKD", texto)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^CJ\.?\s*HAB\.?\s+", "CONJUNTO HABITACIONAL ", s)
    s = re.sub(r"^JD\.?\s+|^JARD\s+|^JAD\s+", "JARDIM ", s)
    s = re.sub(r"^VIL\s+|^VL\.?\s+|^V\.?\s+", "VILA ", s)
    s = re.sub(r"^PQ\.?\s+|^PARQ\s+", "PARQUE ", s)
    s = re.sub(r"^CJ\.?\s+", "CONJUNTO ", s)
    s = re.sub(r"^CH\.?\s+", "CHACARA ", s)
    s = re.sub(r"^FAZ\.?\s+", "FAZENDA ", s)
    s = re.sub(r"\bSTA\b", "SANTA", s)
    s = re.sub(r"\bSTO\b", "SANTO", s)
    s = re.sub(r"\bANTO\b", "ANTONIO", s)
    return s.strip()


def mapear_distrito(bairro):
    """Atribui um bairro a um distrito de saúde."""
    chave = normalizar_bairro(bairro)
    if chave in MAPEAMENTO_DISTRITOS:
        return MAPEAMENTO_DISTRITOS[chave]
    for ref, distrito in MAPEAMENTO_DISTRITOS.items():
        if ref in chave or chave in ref:
            return distrito
    return "OUTROS"


def coord_valida(lat, lon):
    """Verifica se a coordenada está dentro do BBox de Campinas."""
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if lat == 0 or lon == 0:
        return False
    return (BBOX["lat_min"] <= lat <= BBOX["lat_max"]
            and BBOX["lon_min"] <= lon <= BBOX["lon_max"])


def etapa_2_normalizar_colunas(df_raw):
    """
    Pega o DataFrame bruto do CNES (com nomes de coluna longos)
    e gera um DataFrame com nomes amigáveis e tipos corretos.
    """
    df = pd.DataFrame()
    df["codigo_cnes"] = df_raw["codigo_cnes"].astype(str)
    df["nome_fantasia"] = (
        df_raw["nome_fantasia"].fillna(df_raw["nome_razao_social"])
    )
    df["codigo_tipo_unidade"] = (
        df_raw["codigo_tipo_unidade"]
        .astype("Int64").astype(str).str.zfill(2)
    )
    df["descricao_tipo_unidade"] = df_raw["codigo_tipo_unidade"].map(
        lambda c: TIPOS_CNES.get(int(c), f"TIPO {c}")
        if pd.notna(c) else ""
    )
    df["latitude"] = pd.to_numeric(
        df_raw["latitude_estabelecimento_decimo_grau"], errors="coerce"
    )
    df["longitude"] = pd.to_numeric(
        df_raw["longitude_estabelecimento_decimo_grau"], errors="coerce"
    )
    df["bairro_estabelecimento"] = (
        df_raw["bairro_estabelecimento"].fillna("")
    )
    df["vinculo_sus"] = (
        df_raw["estabelecimento_faz_atendimento_ambulatorial_sus"]
        .fillna("NAO")
    )
    df["natureza"] = df_raw["descricao_esfera_administrativa"].fillna("")
    return df


def etapa_2_tratar(df):
    """
    Aplica todas as etapas de limpeza nos dados normalizados:
      1. Filtra por tipo (UBS, Hospital, UPA)
      2. Adiciona coluna 'categoria'
      3. Mapeia bairro → distrito de saúde
      4. Valida coordenadas
      5. Remove duplicatas
    """
    print("\n[ETAPA 2] Tratamento e limpeza...")
    n_inicial = len(df)

    df["codigo_tipo_unidade"] = (
        df["codigo_tipo_unidade"].astype(str).str.zfill(2)
    )
    df = df[df["codigo_tipo_unidade"].isin(CATEGORIA_FOCO.keys())].copy()
    n_filtrado = len(df)

    df["categoria"] = df["codigo_tipo_unidade"].map(CATEGORIA_FOCO)
    df["regiao"] = df["bairro_estabelecimento"].map(mapear_distrito)
    df["distrito_saude"] = df["regiao"]

    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    mask = df.apply(
        lambda r: coord_valida(r["latitude"], r["longitude"]), axis=1
    )
    df = df[mask]
    n_validos = len(df)

    df = df.drop_duplicates(subset=["codigo_cnes"]).reset_index(drop=True)

    print(f"  Brutos:           {n_inicial:>5}")
    print(f"  Após filtro tipo: {n_filtrado:>5}")
    print(f"  Coords válidas:   {n_validos:>5}")
    print(f"  Sem duplicatas:   {len(df):>5}  ← final")
    return df


def etapa_2_indicadores(df_estab, pop_total):
    """Gera indicadores por distrito (hab/UBS, cobertura etc)."""
    print("\n[ETAPA 2] Calculando indicadores por distrito...")

    # Distribui a população total nas proporções da SMS
    pop_distritos = {k: int(round(pop_total * p))
                     for k, p in PROPORCOES_SMS.items()}
    diff = pop_total - sum(pop_distritos.values())
    pop_distritos["SUDOESTE"] += diff  # ajuste de arredondamento

    pivot = (
        df_estab.groupby(["regiao", "categoria"]).size()
        .unstack(fill_value=0).reset_index()
    )
    for c in ["UBS", "Hospital", "UPA"]:
        if c not in pivot.columns:
            pivot[c] = 0

    pivot["populacao"] = (
        pivot["regiao"].map(pop_distritos).fillna(0).astype(int)
    )
    pivot["lat"] = pivot["regiao"].map(
        lambda r: CENTROIDES.get(r, (0, 0))[0])
    pivot["lon"] = pivot["regiao"].map(
        lambda r: CENTROIDES.get(r, (0, 0))[1])
    pivot["total_unidades"] = (
        pivot["UBS"] + pivot["Hospital"] + pivot["UPA"]
    )
    pivot["hab_por_ubs"] = pivot.apply(
        lambda r: round(r["populacao"] / r["UBS"], 0)
        if r["UBS"] > 0 else 0, axis=1)

    def classificar(h):
        if h == 0:
            return "Sem UBS"
        if h <= 10000:
            return "Boa"
        if h <= 20000:
            return "Moderada"
        return "Crítica"

    pivot["cobertura"] = pivot["hab_por_ubs"].apply(classificar)
    df_indic = (
        pivot.sort_values("hab_por_ubs", ascending=False)
        .reset_index(drop=True)
    )
    return df_indic, pop_distritos

# =====================================================================
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  ETAPA 3 — EXPORTAÇÃO CSV → DOCUMENTOS JSON                       ║
# ║                                                                   ║
# ║  STATUS: JÁ EXECUTADA — não precisa rodar novamente               ║
# ║                                                                   ║
# ║  O que foi feito:                                                 ║
# ║    Os dados tratados, que estavam em formato tabular (CSV),       ║
# ║    foram transformados em documentos JSON com estrutura aninhada  ║
# ║    (objetos dentro de objetos). Esse formato é o que o MongoDB    ║
# ║    nativamente utiliza, aproveitando seu paradigma orientado a    ║
# ║    documentos.                                                    ║
# ║                                                                   ║
# ║  Exemplo de transformação:                                        ║
# ║                                                                   ║
# ║  CSV (plano):                                                     ║
# ║    codigo_cnes, nome, codigo_tipo, descricao_tipo, categoria,...  ║
# ║                                                                   ║
# ║  JSON (aninhado):                                                 ║
# ║    {                                                              ║
# ║      "_id": "9636404",                                            ║
# ║      "nome": "UBS Centro",                                        ║
# ║      "tipo": {                                                    ║
# ║        "codigo": "02",                                            ║
# ║        "descricao": "CENTRO DE SAÚDE / UNIDADE BÁSICA",           ║
# ║        "categoria": "UBS"                                         ║
# ║      },                                                           ║
# ║      "endereco": { "bairro": "CENTRO", "regiao": "LESTE" },       ║
# ║      "localizacao": {                                             ║
# ║        "type": "Point",                                           ║
# ║        "coordinates": [-47.06, -22.90]                            ║
# ║      },                                                           ║
# ║      "vinculo_sus": true                                          ║
# ║    }                                                              ║
# ╚═══════════════════════════════════════════════════════════════════╝
# =====================================================================

def etapa_3_csv_para_documentos(df_estab, df_indic):
    """
    Converte os DataFrames tratados em listas de dicionários Python
    (que serão inseridos como documentos JSON no MongoDB).
    Retorna 3 listas: regiões, estabelecimentos, relações.
    """
    print("\n[ETAPA 3] Convertendo CSV → documentos JSON...")

    # --- Coleção 1: regiões (5 documentos) ---
    docs_regioes = []
    for _, r in df_indic.iterrows():
        docs_regioes.append({
            "_id": r["regiao"],
            "regiao": r["regiao"],
            "populacao": int(r["populacao"]),
            "centroide": {                            # objeto aninhado
                "type": "Point",                      # padrão GeoJSON
                "coordinates": [float(r["lon"]),
                                float(r["lat"])],
            },
            "unidades": {                             # objeto aninhado
                "ubs": int(r["UBS"]),
                "hospital": int(r["Hospital"]),
                "upa": int(r["UPA"]),
                "total": int(r["total_unidades"]),
            },
            "indicadores": {                          # objeto aninhado
                "hab_por_ubs": float(r["hab_por_ubs"]),
                "cobertura": r["cobertura"],
            },
        })

    # --- Coleção 2: estabelecimentos (115 documentos) ---
    docs_estab = []
    for _, e in df_estab.iterrows():
        docs_estab.append({
            "_id": str(e["codigo_cnes"]),
            "nome": e["nome_fantasia"],
            "tipo": {                                 # objeto aninhado
                "codigo": str(e["codigo_tipo_unidade"]),
                "descricao": e["descricao_tipo_unidade"],
                "categoria": e["categoria"],
            },
            "endereco": {                             # objeto aninhado
                "bairro": e["bairro_estabelecimento"],
                "regiao": e["regiao"],
            },
            "localizacao": {                          # objeto aninhado
                "type": "Point",                      # padrão GeoJSON
                "coordinates": [float(e["longitude"]),
                                float(e["latitude"])],
            },
            "vinculo_sus": str(e["vinculo_sus"]).upper() == "SIM",
            "natureza": e["natureza"],
        })

    # --- Coleção 3: relações (115 documentos - auxiliar do grafo) ---
    docs_relacoes = []
    for _, e in df_estab.iterrows():
        docs_relacoes.append({
            "regiao": e["regiao"],
            "codigo_cnes": str(e["codigo_cnes"]),
            "nome": e["nome_fantasia"],
            "categoria": e["categoria"],
        })

    # Salva também os JSONs em disco (como evidência da etapa)
    for nome, docs in [("regioes", docs_regioes),
                       ("estabelecimentos", docs_estab),
                       ("relacoes", docs_relacoes)]:
        caminho = DATA_DIR / f"{nome}.json"
        caminho.write_text(
            json.dumps(docs, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"  ✓ {nome}.json ({len(docs)} documentos)")

    return docs_regioes, docs_estab, docs_relacoes

# =====================================================================
# ╔═══════════════════════════════════════════════════════════════════╗
# ║  ETAPA 4 — CARGA NO MONGODB ATLAS                                 ║
# ║                                                                   ║
# ║  STATUS: JÁ EXECUTADA — não precisa rodar novamente               ║
# ║                                                                   ║
# ║  O que foi feito:                                                 ║
# ║    Os documentos JSON gerados na Etapa 3 foram inseridos nas 3    ║
# ║    coleções do MongoDB Atlas (banco saude_campinas), seguidos     ║
# ║    da criação de índices (incluindo 2 índices geoespaciais        ║
# ║    do tipo 2dsphere e 1 índice textual TEXT).                     ║
# ║                                                                   ║
# ║  Os dados permanecem no Atlas indefinidamente.                    ║
# ║  Para acessá-los: utilizar apenas a ETAPA 5.                      ║
# ╚═══════════════════════════════════════════════════════════════════╝
# =====================================================================

def etapa_4_carregar_no_atlas(docs_regioes, docs_estab, docs_relacoes,
                               mongo_uri, *, confirmar_sobrescrita=False):
    """
    Conecta no MongoDB Atlas e insere os documentos nas 3 coleções,
    seguido da criação dos índices.

    ATENÇÃO: executa drop() nas coleções regioes, estabelecimentos e
    relacoes do banco "saude_campinas". Desativada por padrão: só roda
    com confirmar_sobrescrita=True.
    """
    if not confirmar_sobrescrita:
        raise RuntimeError(
            "ETAPA 4 DESATIVADA POR PADRÃO: ela apaga (drop) as coleções "
            "regioes, estabelecimentos e relacoes do banco 'saude_campinas' "
            "no Atlas antes de recarregá-las. Para executar de fato, chame "
            "com confirmar_sobrescrita=True."
        )
    from pymongo import MongoClient, GEOSPHERE, ASCENDING, TEXT
    import certifi

    print("\n[ETAPA 4] Carregando no MongoDB Atlas...")

    # Escapa caracteres especiais da senha (se houver)
    m = re.match(r"(mongodb(?:\+srv)?://)([^:]+):([^@]+)@(.+)", mongo_uri)
    if m:
        schema, user, password, rest = m.groups()
        mongo_uri = (
            f"{schema}{quote_plus(user)}:{quote_plus(password)}@{rest}"
        )

    client = MongoClient(mongo_uri, tlsCAFile=certifi.where(),
                         serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client["saude_campinas"]
    print("  ✓ Conectado no Atlas")

    # Limpa coleções antigas (operação idempotente)
    db.regioes.drop()
    db.estabelecimentos.drop()
    db.relacoes.drop()

    # Insere os documentos
    db.regioes.insert_many(docs_regioes)
    db.estabelecimentos.insert_many(docs_estab)
    db.relacoes.insert_many(docs_relacoes)

    # Cria os índices (7 criados explicitamente abaixo)
    db.regioes.create_index([("centroide", GEOSPHERE)])
    db.regioes.create_index([("indicadores.cobertura", ASCENDING)])
    db.estabelecimentos.create_index([("localizacao", GEOSPHERE)])
    db.estabelecimentos.create_index([("tipo.categoria", ASCENDING)])
    db.estabelecimentos.create_index([("endereco.regiao", ASCENDING)])
    db.estabelecimentos.create_index([("nome", TEXT)])
    db.relacoes.create_index(
        [("regiao", ASCENDING), ("categoria", ASCENDING)]
    )

    print(f"  ✓ regioes:          {db.regioes.count_documents({})} docs")
    print(f"  ✓ estabelecimentos: {db.estabelecimentos.count_documents({})} docs")
    print(f"  ✓ relacoes:         {db.relacoes.count_documents({})} docs")
    return db