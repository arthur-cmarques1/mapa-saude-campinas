# -*- coding: utf-8 -*-
"""Extrai os contornos dos distritos do mapa publicado no Plano Municipal de Saúde.

O plano traz o mapa só como imagem (pág. 75 do PDF), sem dados geográficos. Este
script separa cada distrito pela cor da legenda, encaixa a imagem no limite do
município (IBGE) e grava os polígonos em data/referencia/zonas_distritos.geojson.
O resultado é conferido com as UBS, cujo distrito é conhecido pela tabela oficial.

    pip install pymupdf scipy shapely numpy
    python scripts/extrair_zonas_distritos.py caminho/para/PMS_2026-2029.pdf
"""

import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
import shapely
from scipy import ndimage, optimize
from shapely.geometry import box, mapping, shape

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIA = RAIZ / "data" / "referencia"
SAIDA = REFERENCIA / "zonas_distritos.geojson"

PAGINA_MAPA = 75
# Centro de cada quadrado da legenda na imagem (x, y).
LEGENDA = {
    "LESTE": (800, 449), "NOROESTE": (800, 468), "NORTE": (800, 488),
    "SUDOESTE": (800, 507), "SUL": (800, 527), "SUDESTE": (800, 546),
}
# Título, seta do norte, legenda e escala não fazem parte do mapa.
AREAS_FORA = [(0, 0, 886, 52), (55, 110, 135, 215), (675, 405, 886, 626), (470, 520, 675, 626)]
TOLERANCIA_COR = 30
MENOR_FRAGMENTO = 150              # em pixels da imagem; cada pixel tem cerca de 70 m de lado
TOLERANCIA_SIMPLIFICACAO = 0.0006  # cerca de 60 m
AREA_MINIMA = 2e-5                 # descarta farelos de cerca de 20 hectares


def ler_imagem(caminho_pdf):
    doc = pymupdf.open(caminho_pdf)
    imagens = [i for i in doc[PAGINA_MAPA - 1].get_images(full=True) if i[2] > 300]
    pix = pymupdf.Pixmap(doc, imagens[0][0])
    if pix.n - pix.alpha > 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(float)


def classificar(imagem):
    """Devolve a matriz de classes (-1 = não é cor de distrito) e a lista de nomes."""
    nomes = list(LEGENDA)
    cores = np.array([np.median(imagem[y - 3:y + 4, x - 8:x + 9].reshape(-1, 3), axis=0)
                      for x, y in LEGENDA.values()])
    distancias = np.linalg.norm(imagem[:, :, None, :] - cores[None, None, :, :], axis=3)
    classes = distancias.argmin(axis=2)
    classes[distancias.min(axis=2) > TOLERANCIA_COR] = -1
    for x0, y0, x1, y1 in AREAS_FORA:
        classes[y0:y1, x0:x1] = -1
    # A compressão da imagem cria borrões de outra cor em volta das letras e das linhas.
    for i in range(len(nomes)):
        rotulos, _ = ndimage.label(classes == i)
        tamanhos = np.bincount(rotulos.ravel())
        pequenos = np.flatnonzero(tamanhos < MENOR_FRAGMENTO)
        classes[np.isin(rotulos, pequenos) & (rotulos > 0)] = -1
    return classes, nomes


def mascara_do_municipio(classes):
    colorido = ndimage.binary_closing(classes >= 0, iterations=2)
    rotulos, _ = ndimage.label(colorido)
    maior = np.bincount(rotulos.ravel())[1:].argmax() + 1
    return ndimage.binary_fill_holes(rotulos == maior)


def encaixar(mascara, municipio):
    """Acha a escala e a posição que melhor sobrepõem a imagem ao limite do IBGE."""
    linhas, colunas = np.nonzero(mascara)
    lon0, lat0, lon1, lat1 = municipio.bounds
    inicial = np.array([
        (lon1 - lon0) / (colunas.max() - colunas.min() + 1), lon0 - colunas.min() * (lon1 - lon0) / (colunas.max() - colunas.min() + 1),
        -(lat1 - lat0) / (linhas.max() - linhas.min() + 1), lat1 + linhas.min() * (lat1 - lat0) / (linhas.max() - linhas.min() + 1),
    ])
    altura, largura = mascara.shape
    grade_x, grade_y = np.meshgrid(np.arange(largura) + .5, np.arange(altura) + .5)
    shapely.prepare(municipio)

    def custo(p):
        dentro = shapely.contains_xy(municipio, p[0] * grade_x + p[1], p[2] * grade_y + p[3])
        return -(dentro & mascara).sum() / (dentro | mascara).sum()

    r = optimize.minimize(custo, inicial, method="Nelder-Mead",
                          options={"xatol": 1e-6, "fatol": 1e-5, "maxiter": 700,
                                   "initial_simplex": inicial + np.vstack([np.zeros(4), np.diag([3e-6, 5e-4, 3e-6, 5e-4])])})
    return r.x, -r.fun


def vetorizar(classes, nomes, parametros, municipio):
    """Preenche linhas e textos com a cor mais próxima e converte em polígonos."""
    indices = ndimage.distance_transform_edt(classes < 0, return_distances=False, return_indices=True)
    cheio = classes[tuple(indices)]
    a, b, c, d = parametros
    geometrias = []
    for i in range(len(nomes)):
        retangulos = []
        for y in range(cheio.shape[0]):
            bordas = np.flatnonzero(np.diff(np.r_[0, (cheio[y] == i).astype(int), 0]))
            for x0, x1 in zip(bordas[::2], bordas[1::2]):
                retangulos.append(box(a * x0 + b, c * (y + 1) + d, a * x1 + b, c * y + d))
        geometrias.append(shapely.union_all(retangulos))
    # A simplificação em conjunto mantém a fronteira comum: não abre vão entre vizinhos.
    simplificadas = shapely.coverage_simplify(geometrias, TOLERANCIA_SIMPLIFICACAO)
    zonas = {}
    for nome, geometria in zip(nomes, simplificadas):
        recorte = shapely.make_valid(geometria).intersection(municipio)
        partes = [p for p in getattr(recorte, "geoms", [recorte]) if p.geom_type == "Polygon" and p.area >= AREA_MINIMA]
        zonas[nome] = shapely.set_precision(shapely.MultiPolygon(partes), 1e-5)
    return zonas


def ponto_do_rotulo(geometria):
    lon, lat = shapely.maximum_inscribed_circle(geometria, tolerance=1e-4).coords[0]
    return [round(lat, 5), round(lon, 5)]


def conferir(zonas):
    """Mede quantas unidades de distrito conhecido caem na zona certa."""
    referencia = json.loads((REFERENCIA / "sms_campinas.json").read_text(encoding="utf-8"))
    bruto = json.loads((RAIZ / "data" / "brutos" / "cnes_recorte.json").read_text(encoding="utf-8"))
    correcoes = json.loads((REFERENCIA / "correcoes_coordenadas.json").read_text(encoding="utf-8"))
    conhecidos = {u["cnes"]: u["distrito"] for u in referencia["unidades"]}
    conhecidos.update(referencia["servicos_por_distrito"])
    acertos, erros = 0, []
    for r in bruto["registros"]:
        cnes = str(r["codigo_cnes"])
        if cnes not in conhecidos:
            continue
        lat = correcoes.get(cnes, {}).get("lat", r["latitude_estabelecimento_decimo_grau"])
        lon = correcoes.get(cnes, {}).get("lon", r["longitude_estabelecimento_decimo_grau"])
        ponto = shapely.Point(lon, lat)
        achado = next((n for n, g in zonas.items() if g.covers(ponto)), None)
        if achado == conhecidos[cnes]:
            acertos += 1
        else:
            distancia = zonas[conhecidos[cnes]].distance(ponto) * 111
            erros.append((r["nome_fantasia"], conhecidos[cnes], achado, round(distancia, 2)))
    return acertos, acertos + len(erros), erros


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.stdout.reconfigure(encoding="utf-8")
    limite = json.loads((REFERENCIA / "limite_campinas.geojson").read_text(encoding="utf-8"))
    municipio = shapely.union_all([shape(f["geometry"]) for f in limite["features"]])

    imagem = ler_imagem(sys.argv[1])
    classes, nomes = classificar(imagem)
    mascara = mascara_do_municipio(classes)
    parametros, iou = encaixar(mascara, municipio)
    print(f"Encaixe no limite do IBGE (IoU): {iou:.3f}")

    zonas = vetorizar(classes, nomes, parametros, municipio)
    uniao = shapely.union_all(list(zonas.values()))
    print(f"Área coberta: {uniao.area / municipio.area:.2%}")
    km2 = 111.32 ** 2 * np.cos(np.radians(22.9))
    for nome, geometria in zonas.items():
        print(f"  {nome:9} {geometria.area * km2:6.0f} km²  {len(geometria.geoms)} parte(s)")
    print(f"  soma {uniao.area * km2:.0f} km²")

    acertos, total, erros = conferir(zonas)
    print(f"Unidades na zona certa: {acertos} de {total}")
    for erro in erros:
        print(f"  {erro[0][:42]:42} oficial={erro[1]:9} mapa={erro[2]} a {erro[3]} km da zona")

    saida = {
        "type": "FeatureCollection",
        "fonte": "Mapa de distritos do Plano Municipal de Saúde de Campinas 2026-2029, encaixado na malha do IBGE",
        "features": [{
            "type": "Feature",
            # O centro do maior círculo que cabe na zona é onde o nome do distrito fica legível.
            "properties": {"regiao": n, "rotulo": ponto_do_rotulo(g)},
            "geometry": mapping(g),
        } for n, g in zonas.items()],
    }
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Gravado {SAIDA.relative_to(RAIZ)} ({SAIDA.stat().st_size / 1000:.0f} kB)")


if __name__ == "__main__":
    main()
