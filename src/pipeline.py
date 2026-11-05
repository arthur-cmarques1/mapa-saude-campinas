# -*- coding: utf-8 -*-
"""Pipeline do projeto: coleta, tratamento e carga. Pode ser reexecutado.

    python src/pipeline.py                  # refaz data/ a partir do recorte salvo
    python src/pipeline.py --coletar        # baixa o CNES atual e refaz data/
    python src/pipeline.py --carregar-atlas --confirmar   # substitui as coleções no Atlas

O código original do grupo está na tag v1.0. O distrito agora vem da lista
oficial da Secretaria de Saúde, e não de uma comparação de textos de bairro.
"""

import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicadores  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DATA_DIR = RAIZ / "data"
ARQ_BRUTO = DATA_DIR / "brutos" / "cnes_recorte.json"
ARQ_REFERENCIA = DATA_DIR / "referencia" / "sms_campinas.json"
ARQ_CORRECOES = DATA_DIR / "referencia" / "correcoes_coordenadas.json"

COD_MUNICIPIO_CNES = 350950
COD_MUNICIPIO_IBGE = 3509502
URL_CNES = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
URL_SIDRA = f"https://apisidra.ibge.gov.br/values/t/4709/n6/{COD_MUNICIPIO_IBGE}/v/93/p/last"
TAMANHO_LOTE = 20

# Tipos de unidade do CNES que interessam ao projeto.
TIPOS = {
    1: "POSTO DE SAÚDE",
    2: "CENTRO DE SAÚDE / UNIDADE BÁSICA",
    5: "HOSPITAL GERAL",
    7: "HOSPITAL ESPECIALIZADO",
    73: "PRONTO ATENDIMENTO",
}
CATEGORIA_POR_TIPO = {1: "UBS", 2: "UBS", 5: "Hospital", 7: "Hospital", 73: "UPA"}

# Só estes campos são guardados do CNES. E-mail e CNPJ não são usados no painel.
CAMPOS_BRUTOS = (
    "codigo_cnes", "nome_fantasia", "nome_razao_social", "codigo_tipo_unidade",
    "codigo_cep_estabelecimento", "endereco_estabelecimento", "numero_estabelecimento",
    "bairro_estabelecimento", "numero_telefone_estabelecimento",
    "latitude_estabelecimento_decimo_grau", "longitude_estabelecimento_decimo_grau",
    "descricao_turno_atendimento", "estabelecimento_faz_atendimento_ambulatorial_sus",
    "descricao_natureza_juridica_estabelecimento",
    "codigo_motivo_desabilitacao_estabelecimento", "data_atualizacao",
)


# ─── Etapa 1: coleta ─────────────────────────────────────────────────
def _get_json(url, params=None, tentativas=5, espera=2.0):
    """GET com novas tentativas: a API do CNES oscila com frequência."""
    import requests

    for tentativa in range(1, tentativas + 1):
        try:
            resposta = requests.get(url, params=params, timeout=60)
            resposta.raise_for_status()
            return resposta.json()
        except (requests.RequestException, ValueError) as erro:
            if tentativa == tentativas:
                raise RuntimeError(f"Falha ao consultar {url}: {erro}") from erro
            time.sleep(espera * tentativa)


def coletar_cnes():
    registros = []
    for tipo in TIPOS:
        deslocamento = 0
        while True:
            lote = _get_json(URL_CNES, {
                "codigo_municipio": COD_MUNICIPIO_CNES,
                "codigo_tipo_unidade": tipo,
                "limit": TAMANHO_LOTE,
                "offset": deslocamento,
            }).get("estabelecimentos", [])
            registros.extend(lote)
            deslocamento += TAMANHO_LOTE
            if len(lote) < TAMANHO_LOTE:
                break
            time.sleep(0.2)
        print(f"  tipo {tipo:>2}: {len(registros)} registros acumulados")
    if not registros:
        raise RuntimeError("O CNES não devolveu registros; data/ não foi alterado.")
    recorte = [{campo: r.get(campo) for campo in CAMPOS_BRUTOS} for r in registros]
    recorte.sort(key=lambda r: int(r["codigo_cnes"]))
    return {"coletado_em": date.today().isoformat(), "registros": recorte}


def conferir_populacao(referencia):
    """Confere o total do plano municipal contra o SIDRA/IBGE."""
    valor = int(_get_json(URL_SIDRA)[1]["V"])
    if valor != referencia["populacao_municipio"]:
        raise RuntimeError(f"SIDRA informa {valor}; o plano municipal soma "
                           f"{referencia['populacao_municipio']}.")
    print(f"  população conferida no SIDRA: {valor}")


# ─── Etapa 2: tratamento ─────────────────────────────────────────────
def distancia_km(lat1, lon1, lat2, lon2):
    """Distância em linha reta (fórmula de haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _natureza(codigo):
    """Traduz a natureza jurídica do CNES. O 1º dígito indica o grupo."""
    grupo = str(codigo or "").strip()[:1]
    return {"1": "Pública", "2": "Privada", "3": "Sem fins lucrativos"}.get(grupo, "Não informada")


def _motivo_exclusao(registro, cnes_oficiais):
    cnes = str(registro["codigo_cnes"])
    categoria = CATEGORIA_POR_TIPO[registro["codigo_tipo_unidade"]]
    if registro["codigo_motivo_desabilitacao_estabelecimento"]:
        return "desabilitada no CNES"
    if not registro["latitude_estabelecimento_decimo_grau"]:
        return "sem coordenadas no CNES"
    if categoria == "UBS" and cnes not in cnes_oficiais:
        return "fora da lista oficial de UBS da Secretaria de Saúde"
    sus = registro["estabelecimento_faz_atendimento_ambulatorial_sus"] == "SIM"
    if categoria == "UPA" and not sus:
        return "pronto atendimento sem vínculo SUS"
    return None


def _documento_estabelecimento(registro, distrito, metodo, oficial):
    tipo = registro["codigo_tipo_unidade"]
    nome = registro["nome_fantasia"] or registro["nome_razao_social"]
    return {
        "_id": str(registro["codigo_cnes"]),
        "nome": " ".join(str(nome).split()),
        "tipo": {
            "codigo": str(tipo),
            "descricao": TIPOS[tipo],
            "categoria": CATEGORIA_POR_TIPO[tipo],
        },
        "endereco": {
            "logradouro": (registro["endereco_estabelecimento"] or "").strip(),
            "numero": (registro["numero_estabelecimento"] or "").strip(),
            "bairro": (registro["bairro_estabelecimento"] or "").strip(),
            "cep": (registro["codigo_cep_estabelecimento"] or "").strip(),
            "regiao": distrito,
            "regiao_origem": metodo,
        },
        "localizacao": {
            "type": "Point",
            "coordinates": [
                float(registro["longitude_estabelecimento_decimo_grau"]),
                float(registro["latitude_estabelecimento_decimo_grau"]),
            ],
        },
        "telefone": (registro["numero_telefone_estabelecimento"] or "").strip(),
        "turno": (registro["descricao_turno_atendimento"] or "").strip(),
        "vinculo_sus": registro["estabelecimento_faz_atendimento_ambulatorial_sus"] == "SIM",
        "natureza": _natureza(registro["descricao_natureza_juridica_estabelecimento"]),
        "atualizado_em": registro["data_atualizacao"],
        "equipes": oficial["esf"] if oficial else None,
        "populacao_ibge": oficial["populacao_ibge"] if oficial else None,
        "populacao_cadastrada": oficial["populacao_cadastrada"] if oficial else None,
    }


def tratar(bruto, referencia, correcoes_coordenadas=None):
    """Transforma o recorte do CNES nos documentos das coleções.

    O distrito de cada unidade vem, nesta ordem: da tabela oficial de UBS, da
    lista de serviços de cada distrito no plano municipal e, para os demais
    hospitais, da UBS mais próxima (origem registrada em endereco.regiao_origem).
    """
    oficiais = {u["cnes"]: u for u in referencia["unidades"]}
    servicos = referencia["servicos_por_distrito"]
    correcoes = correcoes_coordenadas or {}

    mantidos, excluidos = [], []
    vistos = set()
    for original in bruto["registros"]:
        registro = dict(original)
        cnes = str(registro["codigo_cnes"])
        if cnes in vistos:
            continue
        vistos.add(cnes)
        if cnes in correcoes:
            registro["latitude_estabelecimento_decimo_grau"] = correcoes[cnes]["lat"]
            registro["longitude_estabelecimento_decimo_grau"] = correcoes[cnes]["lon"]
        motivo = _motivo_exclusao(registro, oficiais)
        if motivo:
            excluidos.append({
                "_id": cnes,
                "nome": " ".join(str(registro["nome_fantasia"] or registro["nome_razao_social"]).split()),
                "categoria": CATEGORIA_POR_TIPO[registro["codigo_tipo_unidade"]],
                "motivo": motivo,
            })
        else:
            mantidos.append(registro)

    faltando = set(oficiais) - {str(r["codigo_cnes"]) for r in mantidos}
    if faltando:
        raise ValueError(f"UBS oficiais ausentes ou desabilitadas no CNES: {sorted(faltando)}")

    ubs = [(float(r["latitude_estabelecimento_decimo_grau"]),
            float(r["longitude_estabelecimento_decimo_grau"]),
            oficiais[str(r["codigo_cnes"])]["distrito"])
           for r in mantidos if str(r["codigo_cnes"]) in oficiais]

    def _ubs_mais_proxima(lat, lon):
        return min(ubs, key=lambda u: distancia_km(lat, lon, u[0], u[1]))[2]

    estabelecimentos = []
    for registro in mantidos:
        cnes = str(registro["codigo_cnes"])
        lat = float(registro["latitude_estabelecimento_decimo_grau"])
        lon = float(registro["longitude_estabelecimento_decimo_grau"])
        if cnes in oficiais:
            distrito, metodo = oficiais[cnes]["distrito"], "tabela oficial de UBS"
        elif cnes in servicos:
            distrito, metodo = servicos[cnes], "serviços do distrito no plano municipal"
        else:
            distrito, metodo = _ubs_mais_proxima(lat, lon), "UBS mais próxima"
        estabelecimentos.append(_documento_estabelecimento(registro, distrito, metodo, oficiais.get(cnes)))

    return {
        "regioes": montar_regioes(estabelecimentos, referencia),
        "estabelecimentos": estabelecimentos,
        "relacoes": [{
            "regiao": e["endereco"]["regiao"],
            "codigo_cnes": e["_id"],
            "nome": e["nome"],
            "categoria": e["tipo"]["categoria"],
        } for e in estabelecimentos],
        "excluidos": excluidos,
    }


def montar_regioes(estabelecimentos, referencia):
    regioes = []
    for distrito, populacao in referencia["populacao_distrito"].items():
        no_distrito = [e for e in estabelecimentos if e["endereco"]["regiao"] == distrito]
        oficiais = [u for u in referencia["unidades"] if u["distrito"] == distrito]
        contar = Counter(e["tipo"]["categoria"] for e in no_distrito if e["vinculo_sus"])
        pontos = [e["localizacao"]["coordinates"] for e in no_distrito if e["tipo"]["categoria"] == "UBS"]
        regioes.append({
            "_id": distrito,
            "regiao": distrito,
            "populacao": populacao,
            "centroide": {
                "type": "Point",
                "coordinates": [
                    round(sum(p[0] for p in pontos) / len(pontos), 5),
                    round(sum(p[1] for p in pontos) / len(pontos), 5),
                ],
            },
            "unidades": {
                "ubs": contar["UBS"],
                "hospital": contar["Hospital"],
                "upa": contar["UPA"],
                "hospital_sem_sus": sum(1 for e in no_distrito
                                        if e["tipo"]["categoria"] == "Hospital" and not e["vinculo_sus"]),
                "total": contar["UBS"] + contar["Hospital"] + contar["UPA"],
            },
            "indicadores": indicadores.indicadores_distrito(oficiais, populacao),
        })
    return sorted(regioes, key=lambda r: r["regiao"])


def metodo_validado(documentos, referencia):
    """Mede o critério 'UBS mais próxima' nas unidades cujo distrito é conhecido."""
    estab = {e["_id"]: e for e in documentos["estabelecimentos"]}
    ubs = [e for e in documentos["estabelecimentos"] if e["tipo"]["categoria"] == "UBS"]
    acertos = total = 0
    for cnes, distrito in referencia["servicos_por_distrito"].items():
        if cnes not in estab:
            continue
        lon, lat = estab[cnes]["localizacao"]["coordinates"]
        vizinha = min(ubs, key=lambda u: distancia_km(lat, lon, u["localizacao"]["coordinates"][1],
                                                      u["localizacao"]["coordinates"][0]))
        acertos += vizinha["endereco"]["regiao"] == distrito
        total += 1
    return {"acertos": acertos, "total": total}


def montar_metadados(bruto, documentos, referencia):
    return {
        "_id": "painel",
        "versao_esquema": 2,
        "cnes_coletado_em": bruto["coletado_em"],
        "fonte_distritos": referencia["fonte"],
        "dependencia_sus": referencia["dependencia_sus"],
        "populacao_municipio": referencia["populacao_municipio"],
        "criterio_ubs_mais_proxima": metodo_validado(documentos, referencia),
    }


def gravar_documentos(documentos, metadados, data_dir=DATA_DIR):
    for nome, conteudo in {**documentos, "metadados": metadados}.items():
        destino = Path(data_dir) / f"{nome}.json"
        destino.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tamanho = len(conteudo) if isinstance(conteudo, list) else 1
        print(f"  {destino.name}: {tamanho} documento(s)")


# ─── Etapa 3: carga no MongoDB Atlas ─────────────────────────────────
def carregar_no_atlas(documentos, metadados, mongo_uri, *, confirmar_sobrescrita=False):
    """Substitui as coleções do banco saude_campinas.

    Os dados entram primeiro em coleções temporárias. As atuais só são trocadas
    depois que tudo foi inserido, então uma falha no meio não apaga o que existe.
    """
    if not confirmar_sobrescrita:
        raise RuntimeError("A carga substitui as coleções do banco saude_campinas. "
                           "Para executar, use confirmar_sobrescrita=True (--confirmar).")
    from pymongo import ASCENDING, GEOSPHERE, TEXT

    import loader

    client = loader.conectar(mongo_uri)
    db = client[loader.NOME_BANCO]
    colecoes = {
        "regioes": documentos["regioes"],
        "estabelecimentos": documentos["estabelecimentos"],
        "relacoes": documentos["relacoes"],
        "metadados": [metadados],
    }
    indices = {
        "regioes": [[("centroide", GEOSPHERE)], [("indicadores.nivel", ASCENDING)]],
        "estabelecimentos": [
            [("localizacao", GEOSPHERE)],
            [("tipo.categoria", ASCENDING)],
            [("endereco.regiao", ASCENDING)],
            [("nome", TEXT)],
        ],
        "relacoes": [[("regiao", ASCENDING), ("categoria", ASCENDING)]],
        "metadados": [],
    }
    try:
        for nome, docs in colecoes.items():
            temporaria = db[f"{nome}__novo"]
            temporaria.drop()
            temporaria.insert_many(docs)
            for indice in indices[nome]:
                temporaria.create_index(indice)
        for nome in colecoes:
            db[f"{nome}__novo"].rename(nome, dropTarget=True)
        return {nome: db[nome].count_documents({}) for nome in colecoes}
    finally:
        client.close()


# ─── Linha de comando ────────────────────────────────────────────────
def _ler_json(caminho):
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def executar(coletar=False, data_dir=DATA_DIR):
    referencia = _ler_json(ARQ_REFERENCIA)
    if coletar:
        print("Baixando o CNES...")
        bruto = coletar_cnes()
        conferir_populacao(referencia)
    else:
        bruto = _ler_json(ARQ_BRUTO)
    print("Tratando...")
    # Valida antes de sobrescrever qualquer arquivo.
    documentos = tratar(bruto, referencia, _ler_json(ARQ_CORRECOES))
    if coletar:
        ARQ_BRUTO.parent.mkdir(parents=True, exist_ok=True)
        ARQ_BRUTO.write_text(json.dumps(bruto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadados = montar_metadados(bruto, documentos, referencia)
    gravar_documentos(documentos, metadados, data_dir)
    return documentos, metadados


def main(argv=None):
    parser = argparse.ArgumentParser(description="Coleta, trata e carrega os dados do painel.")
    parser.add_argument("--coletar", action="store_true", help="baixa o CNES atual antes de tratar")
    parser.add_argument("--carregar-atlas", action="store_true", help="envia os dados ao MongoDB (usa MONGO_URI)")
    parser.add_argument("--confirmar", action="store_true", help="confirma a substituição das coleções")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    documentos, metadados = executar(coletar=args.coletar)
    if args.carregar_atlas:
        import loader

        mongo_uri = loader.obter_uri()
        if not mongo_uri:
            parser.error("defina MONGO_URI (veja .env.example)")
        print("Carregando no MongoDB...")
        print(carregar_no_atlas(documentos, metadados, mongo_uri, confirmar_sobrescrita=args.confirmar))


if __name__ == "__main__":
    main()
