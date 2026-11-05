# -*- coding: utf-8 -*-
"""Gera o painel em um único arquivo HTML, que funciona sem internet.

    python src/dashboard.py            # grava docs/index.html
    python src/dashboard.py --abrir    # grava e abre no navegador
    python src/dashboard.py --saida outro.html   # ou a variável DASHBOARD_SAIDA

Importar este módulo não lê dados nem grava arquivos: quem faz isso é gerar().
"""

import argparse
import csv
import html
import io
import json
import math
import os
import re
import sys
import unicodedata
import webbrowser
from pathlib import Path
from string import Template
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicadores  # noqa: E402
import loader  # noqa: E402

import networkx as nx  # noqa: E402
import plotly.graph_objects as go  # noqa: E402

DIR_SRC = Path(__file__).resolve().parent
DIR_TEMPLATE = DIR_SRC / "template"
DIR_VENDOR = DIR_SRC / "vendor"
SAIDA_PADRAO = loader.RAIZ / "docs" / "index.html"
ARQ_LIMITE = loader.DATA_DIR / "referencia" / "limite_campinas.geojson"

FONTE = "Inter, 'Segoe UI', Roboto, system-ui, -apple-system, sans-serif"
CORES_NIVEL = {
    "Dentro do parâmetro": "#12B48F",
    "Atenção": "#E8A317",
    "Sobrecarga": "#F0784F",
    "Crítico": "#F0587A",
}
CORES_CATEGORIA = {"UBS": "#4F86EA", "Hospital": "#E0446A", "UPA": "#E8A317"}
COR_SEM_SUS = "#8E7BB5"
FATOR_ROTULO_GRAFO = 1.5  # afasta o nome do distrito das unidades ao redor
ROTULO_CATEGORIA = {"UBS": "UBS (posto de saúde)", "Hospital": "Hospital", "UPA": "UPA 24h"}

ACENTOS = {
    "SAUDE": "Saúde", "SAO": "São", "BARAO": "Barão", "CLINICAS": "Clínicas", "CONCEICAO": "Conceição",
    "UNIAO": "União", "MARCO": "Março", "IPE": "Ipê", "ITAJAI": "Itajaí", "AURELIA": "Aurélia",
    "LUCIA": "Lúcia", "MONICA": "Mônica", "VALENCA": "Valença", "INTEGRACAO": "Integração",
    "ROSALIA": "Rosália", "EGIDIO": "Egídio", "ELISEOS": "Elíseos", "CRISTOVAO": "Cristóvão",
    "ANTONIO": "Antônio", "SATELITE": "Satélite", "IRIS": "Íris", "MARIO": "Mário", "JOSE": "José",
    "IRMAOS": "Irmãos", "BENEFICENCIA": "Beneficência", "AMERICA": "América", "ESPERANCA": "Esperança",
    "LOURENCO": "Lourenço", "BARBARA": "Bárbara", "CASSIO": "Cássio", "SERGIO": "Sérgio",
}
MINUSCULAS = {"DE", "DA", "DO", "DAS", "DOS", "E"}
SIGLAS = {"DIC", "UNICAMP", "I", "II", "III", "IV", "V", "VI", "UPA", "UBS", "SOBRAPAR"}
TURNOS = {
    "ATENDIMENTOS NOS TURNOS DA MANHA E A TARDE": "Manhã e tarde",
    "ATENDIMENTO NOS TURNOS DA MANHA, TARDE E NOITE": "Manhã, tarde e noite",
    "ATENDIMENTO CONTINUO DE 24 HORAS/DIA (PLANTAO:INCLUI SABADOS, DOMINGOS E FERIADOS)":
        "24 horas, inclusive fins de semana e feriados",
}


# ─── Formatação ──────────────────────────────────────────────────────
def numero(valor):
    """Inteiro no formato brasileiro: 1139047 -> 1.139.047."""
    return f"{int(round(valor)):,}".replace(",", ".")


def data_br(iso):
    ano, mes, dia = str(iso).split("-")
    return f"{dia}/{mes}/{ano}"


def nome_legivel(texto):
    """Converte 'CENTRO DE SAUDE SAO JOSE' em 'Centro de Saúde São José'."""
    palavras = []
    for i, palavra in enumerate(str(texto).upper().split()):
        if palavra in ACENTOS:
            palavras.append(ACENTOS[palavra])
        elif palavra in SIGLAS:
            palavras.append(palavra)
        elif palavra in MINUSCULAS and i > 0:
            palavras.append(palavra.lower())
        else:
            palavras.append(palavra.capitalize())
    return " ".join(palavras)


def distrito_legivel(nome):
    return str(nome).capitalize()


def sem_acentos(texto):
    decomposto = unicodedata.normalize("NFD", str(texto))
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def link_telefone(telefone):
    """Devolve o destino tel: ou None. Números de 8 dígitos recebem o DDD de Campinas."""
    digitos = re.sub(r"\D", "", str(telefone))
    if len(digitos) == 8:
        digitos = "19" + digitos
    return f"tel:+55{digitos}" if len(digitos) in (10, 11) else None


def e(texto):
    return html.escape(str(texto), quote=True)


def json_para_script(dados):
    """JSON seguro dentro de <script>: um nome com '</script>' não encerra o bloco."""
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"), default=str)
    return texto.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _script_seguro(codigo):
    return codigo.replace("</script", "<\\/script")


# ─── Dados do painel ─────────────────────────────────────────────────
def preparar(documentos):
    df_estab = loader.montar_df_estab(documentos["estabelecimentos"])
    df_indic = loader.montar_df_indic(documentos["regioes"])
    df_estab["is_sus"] = df_estab["vinculo_sus"] == "SIM"
    return df_estab, df_indic, df_estab[df_estab["is_sus"]].reset_index(drop=True), documentos["metadados"]


# ─── Gráficos ────────────────────────────────────────────────────────
def _layout(altura, **extra):
    base = dict(
        template="none", height=altura, separators=",.",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONTE, size=13), margin=dict(l=90, r=36, t=16, b=48),
        hoverlabel=dict(font=dict(family=FONTE)),
    )
    base.update(extra)
    return base


def _linha_vertical(x, rotulo):
    return dict(
        shapes=[dict(type="line", x0=x, x1=x, yref="paper", y0=0, y1=1, line=dict(dash="dash", width=2, color="#12B48F"))],
        annotations=[dict(x=x, y=1.01, yref="paper", yanchor="bottom", text=rotulo, showarrow=False, font=dict(size=12))],
    )


def fig_pressao(df):
    d = df.sort_values("pressao")
    fig = go.Figure(go.Bar(
        x=d["pressao"].tolist(), y=[distrito_legivel(r) for r in d["regiao"]], orientation="h",
        marker=dict(color=[CORES_NIVEL[n] for n in d["nivel"]]),
        text=[f"{p} · {n}" for p, n in zip(d["pressao"], d["nivel"])], textposition="inside",
        insidetextanchor="start", textangle=0, textfont=dict(color="#0A0E1A", size=13),
        customdata=[[numero(c), int(q)] for c, q in zip(d["cadastrados_por_equipe"], d["equipes"])],
        hovertemplate="<b>%{y}</b><br>Pressão: %{x}<br>%{customdata[0]} cadastrados por equipe"
                      "<br>%{customdata[1]} equipes<extra></extra>",
    ))
    fig.update_layout(**_layout(360, margin=dict(l=90, r=20, t=34, b=44), **_linha_vertical(100, "100 = limite recomendado")))
    fig.update_xaxes(range=[0, 135], title="Pressão (cadastrados por equipe; 100 = 3.500 pessoas)")
    return fig


def fig_hab_ubs(df):
    d = df.sort_values("hab_por_ubs")
    fig = go.Figure(go.Bar(
        x=d["hab_por_ubs"].tolist(), y=[distrito_legivel(r) for r in d["regiao"]], orientation="h",
        marker=dict(color="#4F86EA"),
        text=[numero(v) for v in d["hab_por_ubs"]], textposition="inside",
        insidetextanchor="start", textangle=0, textfont=dict(color="#0A0E1A", size=13),
        customdata=[[int(u)] for u in d["UBS"]],
        hovertemplate="<b>%{y}</b><br>%{x:,.0f} moradores por UBS<br>%{customdata[0]} UBS<extra></extra>",
    ))
    fig.update_layout(**_layout(360, margin=dict(l=90, r=20, t=34, b=44),
                                **_linha_vertical(indicadores.REFERENCIA_POR_UBS, "14 mil (4 equipes × 3.500)")))
    fig.update_xaxes(title="Moradores por UBS", tickformat=",.0f", rangemode="tozero")
    return fig


def fig_duas_medidas(df):
    fig = go.Figure(go.Scatter(
        x=df["hab_por_ubs"].tolist(), y=df["cadastrados_por_equipe"].tolist(),
        mode="markers+text", text=[distrito_legivel(r) for r in df["regiao"]], textposition="top center",
        marker=dict(size=18, color=[CORES_NIVEL[n] for n in df["nivel"]], line=dict(width=1, color="#0A0E1A")),
        hovertemplate="<b>%{text}</b><br>%{x:,.0f} moradores por UBS<br>%{y:,.0f} cadastrados por equipe<extra></extra>",
    ))
    fig.update_layout(**_layout(420, margin=dict(l=70, r=30, t=30, b=54)))
    fig.update_xaxes(title="Moradores por UBS", tickformat=",.0f", range=[8000, 27000])
    fig.update_yaxes(title="Cadastrados por equipe", tickformat=",.0f", range=[3300, 4400])
    return fig


def fig_hospitais(df):
    d = df.sort_values("regiao")
    distritos = [distrito_legivel(r) for r in d["regiao"]]
    fig = go.Figure()
    fig.add_bar(name="Atende pelo SUS", x=distritos, y=d["Hospital"].tolist(), marker_color=CORES_CATEGORIA["Hospital"],
                text=[v or "" for v in d["Hospital"]], textposition="inside", textangle=0,
                constraintext="none", textfont=dict(color="#0A0E1A"))
    fig.add_bar(name="Sem atendimento ambulatorial SUS", x=distritos, y=d["hospital_sem_sus"].tolist(), marker_color=COR_SEM_SUS,
                text=[v or "" for v in d["hospital_sem_sus"]], textposition="inside", textangle=0,
                constraintext="none", textfont=dict(color="#0A0E1A"))
    fig.update_layout(**_layout(380, barmode="stack", margin=dict(l=50, r=20, t=16, b=90),
                                legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center")))
    fig.update_yaxes(title="Hospitais", dtick=2)
    return fig


def fig_composicao(df_sus):
    contagem = df_sus["categoria"].value_counts()
    categorias = [c for c in CORES_CATEGORIA if c in contagem.index]
    fig = go.Figure(go.Pie(
        labels=[ROTULO_CATEGORIA[c] for c in categorias], values=[int(contagem[c]) for c in categorias], hole=0.62,
        marker=dict(colors=[CORES_CATEGORIA[c] for c in categorias]), textinfo="value", sort=False,
        textfont=dict(color="#0A0E1A", size=14),
        hovertemplate="<b>%{label}</b><br>%{value} unidades (%{percent})<extra></extra>",
    ))
    fig.update_layout(**_layout(380, margin=dict(l=20, r=20, t=16, b=40),
                                legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center")))
    return fig


def montar_grafo(df_indic, df_sus):
    grafo = nx.Graph()
    for r in df_indic.itertuples():
        grafo.add_node(f"REG::{r.regiao}", tipo="regiao", regiao=r.regiao, nivel=r.nivel, pop=int(r.populacao))
    for u in df_sus.itertuples():
        no = f"EST::{u.codigo_cnes}"
        grafo.add_node(no, tipo=u.categoria, regiao=u.regiao, nome=nome_legivel(u.nome_fantasia))
        grafo.add_edge(f"REG::{u.regiao}", no)
    return grafo


def posicoes_grafo(grafo):
    """Distritos em círculo e unidades em espiral ao redor: determinístico e sem sobreposição."""
    distritos = sorted(n for n, d in grafo.nodes(data=True) if d["tipo"] == "regiao")
    pos = {}
    for i, distrito in enumerate(distritos):
        angulo = 2 * math.pi * i / len(distritos) + math.pi / 2
        cx, cy = math.cos(angulo), math.sin(angulo)
        pos[distrito] = (cx, cy)
        for k, unidade in enumerate(sorted(grafo.neighbors(distrito))):
            raio = 0.075 * math.sqrt(k + 1) + 0.05
            giro = k * math.pi * (3 - math.sqrt(5))
            pos[unidade] = (cx + raio * math.cos(giro), cy + raio * math.sin(giro))
    return pos


def fig_grafo(df_indic, df_sus):
    grafo = montar_grafo(df_indic, df_sus)
    pos = posicoes_grafo(grafo)
    xs, ys = [], []
    for a, b in grafo.edges():
        xs += [pos[a][0], pos[b][0], None]
        ys += [pos[a][1], pos[b][1], None]
    fig = go.Figure()
    fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(width=0.8, color="#7C89A8"), hoverinfo="skip", showlegend=False)
    estilos = {"UBS": 9, "Hospital": 15, "UPA": 13}
    for tipo, tamanho in estilos.items():
        nos = [n for n, d in grafo.nodes(data=True) if d["tipo"] == tipo]
        fig.add_scatter(
            x=[pos[n][0] for n in nos], y=[pos[n][1] for n in nos], mode="markers", name=ROTULO_CATEGORIA[tipo],
            marker=dict(size=tamanho, color=CORES_CATEGORIA[tipo], line=dict(width=1, color="#0A0E1A")),
            text=[f"<b>{e(grafo.nodes[n]['nome'])}</b><br>Distrito {distrito_legivel(grafo.nodes[n]['regiao'])}" for n in nos],
            hoverinfo="text",
        )
    distritos = sorted(n for n, d in grafo.nodes(data=True) if d["tipo"] == "regiao")
    fig.add_scatter(
        x=[pos[n][0] for n in distritos], y=[pos[n][1] for n in distritos], mode="markers", name="Distrito",
        marker=dict(size=24, color="#8FA9E8", line=dict(width=2, color="#0A0E1A")),
        text=[f"<b>{distrito_legivel(grafo.nodes[n]['regiao'])}</b><br>{numero(grafo.nodes[n]['pop'])} moradores<br>"
              f"{grafo.degree(n)} unidades SUS" for n in distritos],
        hoverinfo="text",
    )
    fig.add_scatter(
        x=[pos[n][0] * FATOR_ROTULO_GRAFO for n in distritos], y=[pos[n][1] * FATOR_ROTULO_GRAFO for n in distritos], mode="text",
        text=[f"<b>{distrito_legivel(grafo.nodes[n]['regiao'])}</b>" for n in distritos],
        textfont=dict(size=14), hoverinfo="skip", showlegend=False,
    )
    fig.update_layout(**_layout(620, margin=dict(l=10, r=10, t=10, b=30),
                                legend=dict(orientation="h", y=-0.02, x=0.5, xanchor="center")))
    fig.update_xaxes(visible=False, range=[-1.9, 1.9])
    fig.update_yaxes(visible=False, range=[-1.75, 1.75], scaleanchor="x")
    return fig


def figuras(df_indic, df_estab, df_sus):
    return {nome: json.loads(fig.to_json()) for nome, fig in {
        "g-pressao": fig_pressao(df_indic),
        "g-hab-ubs": fig_hab_ubs(df_indic),
        "g-medidas": fig_duas_medidas(df_indic),
        "g-hospitais": fig_hospitais(df_indic),
        "g-composicao": fig_composicao(df_sus),
        "g-grafo": fig_grafo(df_indic, df_sus),
    }.items()}


# ─── Trechos de HTML ─────────────────────────────────────────────────
def _selo(nivel):
    return f'<span class="selo" style="background:{CORES_NIVEL[nivel]}">{e(nivel)}</span>'


def linhas_tabela(df_indic):
    linhas = []
    for r in df_indic.itertuples():
        linhas.append(
            f'<tr><th scope="row">{e(distrito_legivel(r.regiao))}</th>'
            f"<td>{numero(r.populacao)}</td><td>{r.UBS}</td><td>{r.equipes}</td>"
            f"<td>{r.Hospital}</td><td>{r.UPA}</td><td>{numero(r.hab_por_ubs)}</td>"
            f"<td>{numero(r.hab_por_equipe)}</td><td>{numero(r.cadastrados_por_equipe)}</td>"
            f"<td>{r.pressao}</td><td>{_selo(r.nivel)}</td></tr>"
        )
    return "\n".join(linhas)


def endereco_texto(u):
    numero_casa = "" if str(u.numero).upper() in ("", "S/N", "SN") else f", {u.numero}"
    return f"{nome_legivel(u.logradouro)}{numero_casa} – {nome_legivel(u.bairro_estabelecimento)}"


def cartoes_unidades(df_sus):
    cartoes = []
    ordem = {"UPA": 0, "Hospital": 1, "UBS": 2}
    for u in sorted(df_sus.itertuples(), key=lambda x: (ordem[x.categoria], x.nome_fantasia)):
        nome = nome_legivel(u.nome_fantasia)
        endereco = endereco_texto(u)
        busca = sem_acentos(f"{nome} {u.nome_fantasia} {endereco} {u.regiao} {u.categoria}")
        destino = f"https://www.google.com/maps/dir/?api=1&destination={u.latitude},{u.longitude}"
        tel = link_telefone(u.telefone)
        telefone = (f'<a href="{e(tel)}">Ligar: {e(u.telefone)}</a>' if tel
                    else '<span class="sem-dado">Telefone não informado</span>')
        cartoes.append(f"""<li class="unidade" data-id="{e(u.codigo_cnes)}" data-cat="{e(u.categoria)}" data-regiao="{e(u.regiao)}" data-busca="{e(busca)}" data-lat="{u.latitude}" data-lon="{u.longitude}">
  <h3>{e(nome)}</h3>
  <p class="etiquetas"><span class="etiqueta etiqueta-{e(u.categoria.lower())}">{e(ROTULO_CATEGORIA[u.categoria])}</span> <span class="etiqueta">Distrito {e(distrito_legivel(u.regiao))}</span> <span class="distancia" hidden></span></p>
  <p>{e(endereco)}</p>
  <p class="fraco">Funcionamento no cadastro: {e(TURNOS.get(u.turno, u.turno.capitalize()))}</p>
  <p class="acoes">{telefone} <a href="{e(destino)}" target="_blank" rel="noopener noreferrer">Como chegar<span class="sr"> (abre o Google Maps em nova aba)</span></a> <button type="button" class="ver-no-mapa" hidden>Ver no mapa</button></p>
</li>""")
    return "\n".join(cartoes)


def opcoes_distrito(df_indic):
    return "\n".join(f'<option value="{e(r)}">{e(distrito_legivel(r))}</option>' for r in sorted(df_indic["regiao"]))


def csv_data_uri(linhas, cabecalho):
    """CSV que o Excel em português abre certo: separador ';' e marca UTF-8."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    return "data:text/csv;charset=utf-8," + quote("\ufeff" + buffer.getvalue())


def csvs(df_indic, df_sus):
    distritos = csv_data_uri(
        [[distrito_legivel(r.regiao), r.populacao, r.UBS, r.equipes, r.Hospital, r.UPA, r.hab_por_ubs,
          r.hab_por_equipe, r.populacao_cadastrada, r.cadastrados_por_equipe, r.pressao, r.nivel]
         for r in df_indic.itertuples()],
        ["distrito", "moradores", "ubs", "equipes", "hospitais_sus", "upas", "moradores_por_ubs",
         "moradores_por_equipe", "cadastrados", "cadastrados_por_equipe", "pressao", "situacao"],
    )
    unidades = csv_data_uri(
        [[u.codigo_cnes, nome_legivel(u.nome_fantasia), u.categoria, distrito_legivel(u.regiao),
          endereco_texto(u), u.cep, u.telefone, TURNOS.get(u.turno, u.turno), u.latitude, u.longitude]
         for u in df_sus.itertuples()],
        ["cnes", "nome", "categoria", "distrito", "endereco", "cep", "telefone", "funcionamento", "latitude", "longitude"],
    )
    return distritos, unidades


def conclusoes(df_indic, df_estab, df_sus, metadados):
    """Texto calculado dos dados. Nada aqui depende de um distrito específico."""
    maior_pressao = df_indic.loc[df_indic["cadastrados_por_equipe"].idxmax()]
    menor_pressao = df_indic.loc[df_indic["cadastrados_por_equipe"].idxmin()]
    maior_ubs = df_indic.loc[df_indic["hab_por_ubs"].idxmax()]
    menor_ubs = df_indic.loc[df_indic["hab_por_ubs"].idxmin()]
    acima = int((df_indic["cadastrados_por_equipe"] > indicadores.LIMITE_POR_EQUIPE).sum())
    hosp = df_sus[df_sus["categoria"] == "Hospital"]
    sem_hospital = [distrito_legivel(r) for r in df_indic.loc[df_indic["Hospital"] == 0, "regiao"]]
    mais_hosp = df_indic.loc[df_indic["Hospital"].idxmax()]
    naturezas = hosp["natureza"].value_counts()
    composicao_hosp = ", ".join(f"{int(naturezas[n])} {rotulo}" for n, rotulo in (
        ("Pública", "públicos"), ("Sem fins lucrativos", "sem fins lucrativos"),
        ("Privada", "privados"), ("Não informada", "sem natureza informada"),
    ) if n in naturezas)
    dependencia = metadados["dependencia_sus"]

    if maior_ubs["regiao"] == maior_pressao["regiao"]:
        medidas = (f"As duas medidas apontam para o mesmo lugar: o distrito "
                   f"<b>{e(distrito_legivel(maior_ubs['regiao']))}</b>.")
    else:
        medidas = (f"Contando todos os moradores por UBS, o maior número está no "
                   f"<b>{e(distrito_legivel(maior_ubs['regiao']))}</b> ({numero(maior_ubs['hab_por_ubs'])}). "
                   f"Contando quem está cadastrado por equipe, está no "
                   f"<b>{e(distrito_legivel(maior_pressao['regiao']))}</b> ({numero(maior_pressao['cadastrados_por_equipe'])}). "
                   "Uma explicação possível é que parte dos moradores usa plano de saúde e não se cadastra na UBS, "
                   "mas o plano municipal não publica a dependência do SUS por distrito para confirmar isso.")
    sem_hospital_txt = (f"O{'s distritos' if len(sem_hospital) > 1 else ' distrito'} "
                        f"{e(', '.join(sem_hospital))} não {'têm' if len(sem_hospital) > 1 else 'tem'} hospital com atendimento SUS "
                        "no próprio território. " if sem_hospital else "")
    return "\n".join(f'<div class="conclusao">{t}</div>' for t in [
        f"<b>1. Em {acima} dos {len(df_indic)} distritos, as equipes atendem mais pessoas do que o recomendado.</b> "
        f"A política nacional recomenda de {numero(indicadores.MINIMO_POR_EQUIPE)} a {numero(indicadores.LIMITE_POR_EQUIPE)} "
        f"pessoas por equipe. Os distritos vão de {numero(menor_pressao['cadastrados_por_equipe'])} "
        f"({e(distrito_legivel(menor_pressao['regiao']))}) a {numero(maior_pressao['cadastrados_por_equipe'])} "
        f"({e(distrito_legivel(maior_pressao['regiao']))}) cadastrados por equipe.",
        f"<b>2. A resposta depende de como se mede.</b> {medidas}",
        f"<b>3. O número de UBS varia bastante.</b> Há {numero(menor_ubs['hab_por_ubs'])} moradores por UBS no "
        f"{e(distrito_legivel(menor_ubs['regiao']))} e {numero(maior_ubs['hab_por_ubs'])} no "
        f"{e(distrito_legivel(maior_ubs['regiao']))}. Mais UBS não significa, sozinho, mais equipes: compare as colunas no quadro acima.",
        f"<b>4. Os hospitais SUS não estão distribuídos por igual.</b> O distrito {e(distrito_legivel(mais_hosp['regiao']))} "
        f"tem {int(mais_hosp['Hospital'])} dos {len(hosp)}. {sem_hospital_txt}Hospitais servem à cidade inteira e à região, "
        "então a localização não mede sozinha o acesso.",
        f"<b>5. Atender pelo SUS não é o mesmo que ser público.</b> Dos {len(hosp)} hospitais com atendimento SUS, "
        f"o cadastro indica {composicao_hosp}. "
        f"O Plano Municipal estima que {dependencia['percentual']}% dos moradores, cerca de {numero(dependencia['pessoas'])} pessoas, "
        "dependem do SUS.",
    ])


def aviso_cadastro(df_indic):
    """Distritos com mais cadastrados do que moradores no Censo mostram o limite do cadastro."""
    acima = df_indic[df_indic["populacao_cadastrada"] > df_indic["populacao"]]
    if acima.empty:
        return ""
    casos = "; ".join(f"{distrito_legivel(r.regiao)}: {numero(r.populacao_cadastrada)} cadastrados e "
                      f"{numero(r.populacao)} moradores" for r in acima.itertuples())
    return (f"<li>O cadastro não é uma contagem exata de moradores. Ele pode superar o Censo ({e(casos)}), "
            "por ser mais recente e poder incluir quem se mudou.</li>")


# ─── Montagem ────────────────────────────────────────────────────────
def renderizar(documentos):
    df_estab, df_indic, df_sus, metadados = preparar(documentos)
    limite = json.loads(ARQ_LIMITE.read_text(encoding="utf-8"))
    csv_distritos, csv_unidades = csvs(df_indic, df_sus)
    hosp_sus = int(df_indic["Hospital"].sum())
    hosp_sem = int(df_indic["hospital_sem_sus"].sum())
    criterio = metadados["criterio_ubs_mais_proxima"]
    maior = df_indic.loc[df_indic["cadastrados_por_equipe"].idxmax()]
    acima = int((df_indic["cadastrados_por_equipe"] > indicadores.LIMITE_POR_EQUIPE).sum())

    dados_js = {
        "figuras": figuras(df_indic, df_estab, df_sus),
        "limite": limite,
        "cores": CORES_CATEGORIA,
        "rotulos": ROTULO_CATEGORIA,
    }
    template = Template((DIR_TEMPLATE / "painel.html").read_text(encoding="utf-8"))
    return template.substitute(
        css=(DIR_VENDOR / "leaflet.css").read_text(encoding="utf-8") + (DIR_TEMPLATE / "painel.css").read_text(encoding="utf-8"),
        js_plotly=_script_seguro((DIR_VENDOR / "plotly-basic.min.js").read_text(encoding="utf-8")),
        js_leaflet=_script_seguro((DIR_VENDOR / "leaflet.js").read_text(encoding="utf-8")),
        js_painel=_script_seguro((DIR_TEMPLATE / "painel.js").read_text(encoding="utf-8")),
        dados_json=json_para_script(dados_js),
        populacao=numero(metadados["populacao_municipio"]),
        data_cnes=data_br(metadados["cnes_coletado_em"]),
        n_sus=len(df_sus),
        n_ubs=int(df_indic["UBS"].sum()),
        n_equipes=numero(df_indic["equipes"].sum()),
        n_hosp_sus=hosp_sus,
        n_hosp_sem=hosp_sem,
        n_upa=int(df_indic["UPA"].sum()),
        n_distritos=len(df_indic),
        n_acima=acima,
        maior_distrito=e(distrito_legivel(maior["regiao"])),
        maior_valor=numero(maior["cadastrados_por_equipe"]),
        limite_equipe=numero(indicadores.LIMITE_POR_EQUIPE),
        minimo_equipe=numero(indicadores.MINIMO_POR_EQUIPE),
        n_excluidas=len(documentos.get("excluidos") or []) or "",
        criterio_acertos=criterio["acertos"],
        criterio_total=criterio["total"],
        url_pms=e(metadados["fonte_distritos"]["url"]),
        opcoes_distrito=opcoes_distrito(df_indic),
        linhas_tabela=linhas_tabela(df_indic),
        cartoes=cartoes_unidades(df_sus),
        conclusoes=conclusoes(df_indic, df_estab, df_sus, metadados),
        aviso_cadastro=aviso_cadastro(df_indic),
        csv_distritos=e(csv_distritos),
        csv_unidades=e(csv_unidades),
    )


def caminho_saida(saida=None):
    return Path(saida or os.environ.get("DASHBOARD_SAIDA") or SAIDA_PADRAO)


def gerar(saida=None, mongo_uri=None):
    """Lê os dados, monta o HTML, grava e devolve o caminho do arquivo."""
    documentos = loader.carregar_documentos(mongo_uri=mongo_uri)
    if "excluidos" not in documentos:
        arquivo = loader.DATA_DIR / "excluidos.json"
        documentos["excluidos"] = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.is_file() else []
    destino = caminho_saida(saida)
    conteudo = renderizar(documentos)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_bytes(conteudo.encode("utf-8"))
    temporario.replace(destino)  # um erro no meio não deixa o painel pela metade
    return destino


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gera o painel de saúde de Campinas em um único HTML.")
    parser.add_argument("--saida", help=f"arquivo de saída (padrão: {SAIDA_PADRAO.relative_to(loader.RAIZ)})")
    parser.add_argument("--abrir", action="store_true", help="abre o painel no navegador ao terminar")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(f"Lendo dados de: {loader.fonte_em_uso()}")
    destino = gerar(args.saida)
    print(f"Painel gravado em {destino} ({destino.stat().st_size / 1_000_000:.1f} MB)")
    print("Abra esse arquivo com dois cliques. Ele funciona sem internet e sem instalar nada.")
    if args.abrir:
        webbrowser.open(destino.resolve().as_uri())


if __name__ == "__main__":
    main()
