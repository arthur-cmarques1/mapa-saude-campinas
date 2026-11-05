# -*- coding: utf-8 -*-
# === Dashboard v4: linguagem leiga + grafo NetworkX + filtros corrigidos ===
# Lê df_estab/df_indic de loader.py (JSONs locais em data/ ou MongoDB Atlas
# se MONGO_URI estiver definida). Saída: build/dashboard_gerado.html, ou o
# caminho em DASHBOARD_SAIDA.
# Mudanças vs v3:
#   1. Filtra UBS/UPA não-SUS (artefatos do CNES como penitenciárias)
#   2. Hospitais SUS vs Privados separados explicitamente
#   3. "Risk Score" → "Pressão sobre o SUS" (linguagem leiga)
#   4. Grafo NetworkX clássico (nós + arestas) substitui Sankey
#   5. Radar com rótulos legíveis
#   6. Tom de comunicação pra cidadão
#   7. Seção "Como ler este painel" no topo

import json
import os
import re
import sys
from pathlib import Path

# Consoles do Windows (cp1252) falham com os emojis dos prints.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import loader  # noqa: E402

import networkx as nx
import pandas as pd
import plotly.graph_objects as go


# ─── 1. CARREGA DO ATLAS + LIMPA RUÍDOS ──────────────────────────────
print(f"📡 Carregando dados de: {loader.fonte_em_uso()}")

_estab, _indic = loader.carregar_dados()

# Mesmas colunas que o dashboard v4 original montava a partir do Mongo
df_estab_full = pd.DataFrame({
    "codigo_cnes": _estab["codigo_cnes"],
    "nome":        _estab["nome_fantasia"],
    "categoria":   _estab["categoria"],
    "tipo_desc":   _estab["descricao_tipo_unidade"],
    "bairro":      _estab["bairro_estabelecimento"],
    "regiao":      _estab["regiao"],
    "latitude":    _estab["latitude"],
    "longitude":   _estab["longitude"],
    "is_sus":      _estab["vinculo_sus"] == "SIM",
    "natureza":    _estab["natureza"],
})

# FILTRO: UBS e UPA não-SUS são artefatos do CNES (penitenciárias, CAPS,
# clínicas mal-classificadas). Removemos pra não confundir.
mask_ruido = (
    (df_estab_full["categoria"].isin(["UBS", "UPA"]))
    & (~df_estab_full["is_sus"])
)
df_ruido = df_estab_full[mask_ruido].copy()
df_estab = df_estab_full[~mask_ruido].reset_index(drop=True)

print(f"  ✓ {len(df_estab_full)} estabelecimentos carregados")
print(f"  ✓ {len(df_ruido)} UBS/UPA não-SUS removidas (artefatos)")
print(f"  ✓ {len(df_estab)} estabelecimentos válidos para o painel")

df_sus = df_estab[df_estab["is_sus"]].copy()


# Recalcula indicadores com a base limpa (só SUS)
pivot_sus = (df_sus.groupby(["regiao", "categoria"]).size()
                   .unstack(fill_value=0).reset_index())
for c in ["UBS", "Hospital", "UPA"]:
    if c not in pivot_sus.columns:
        pivot_sus[c] = 0

df_indic = _indic[["regiao", "populacao", "lat", "lon"]].copy()

df_indic = df_indic.merge(pivot_sus, on="regiao", how="left").fillna(0)
df_indic["total_unidades"] = (df_indic["UBS"] + df_indic["Hospital"]
                              + df_indic["UPA"])
df_indic["hab_por_ubs"] = df_indic.apply(
    lambda r: round(r["populacao"] / r["UBS"], 0) if r["UBS"] > 0 else 0,
    axis=1)
for c in ["UBS", "Hospital", "UPA", "total_unidades"]:
    df_indic[c] = df_indic[c].astype(int)


# ─── 2. PRESSÃO SOBRE O SUS (linguagem leiga) ────────────────────────
# Score 0-100: 5.000 hab/UBS = ideal (MS); 20.000+ = grave
def calcular_pressao(hab_por_ubs):
    if hab_por_ubs == 0:
        return 100
    if hab_por_ubs <= 5000:
        return round((hab_por_ubs / 5000) * 25, 0)
    if hab_por_ubs <= 10000:
        return round(25 + ((hab_por_ubs - 5000) / 5000) * 25, 0)
    if hab_por_ubs <= 20000:
        return round(50 + ((hab_por_ubs - 10000) / 10000) * 25, 0)
    return min(100, round(75 + ((hab_por_ubs - 20000) / 50000) * 25, 0))

def nivel_pressao(score):
    if score <= 25: return "Tranquilo"
    if score <= 50: return "Atenção"
    if score <= 75: return "Sobrecarga"
    return "Crítico"

df_indic["pressao"] = df_indic["hab_por_ubs"].apply(calcular_pressao)
df_indic["nivel"] = df_indic["pressao"].apply(nivel_pressao)
df_indic = df_indic.sort_values("pressao", ascending=False).reset_index(drop=True)


# ─── 3. PALETA ───────────────────────────────────────────────────────
PAL = {
    "bg": "#0A0E1A", "bg_card": "#131929", "bg_elevated": "#1A2238",
    "border": "#1E2A45", "text": "#E5EEFF", "text_dim": "#8B95B7",
    "text_muted": "#5B6584", "primary": "#5B8DEF", "accent": "#00D4AA",
    "warn": "#FFB547", "crit": "#FF5C7C", "ok": "#00D4AA",
    "ubs": "#5B8DEF", "hospital": "#FF5C7C", "hospital_pv": "#7F5C99",
    "upa": "#FFB547",
}

CORES_NIVEL = {
    "Tranquilo": PAL["ok"], "Atenção": PAL["warn"],
    "Sobrecarga": "#FF8A6E", "Crítico": PAL["crit"],
}

def base_layout(height=380, title=""):
    return dict(
        title=dict(text=f"<b>{title}</b>",
                   font=dict(color=PAL["text"], size=14, family="Inter")),
        height=height, template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", size=12,
                  color=PAL["text_dim"]),
        margin=dict(l=20, r=20, t=60, b=20),
    )


# ─── 4. GRÁFICOS ─────────────────────────────────────────────────────

# G1: Pressão sobre o SUS
df_p = df_indic.sort_values("pressao", ascending=True)
g1 = go.Figure(go.Bar(
    x=df_p["pressao"], y=df_p["regiao"], orientation="h",
    marker=dict(color=[CORES_NIVEL[n] for n in df_p["nivel"]],
                line=dict(width=0)),
    text=df_p["pressao"].apply(lambda v: f"{v:.0f}"),
    textposition="outside",
    textfont=dict(color=PAL["text"], size=13),
    customdata=df_p[["nivel", "populacao", "UBS"]].values,
    hovertemplate=("<b>%{y}</b><br>"
                   "Nível de pressão: %{x:.0f}/100<br>"
                   "Situação: %{customdata[0]}<br>"
                   "População: %{customdata[1]:,}<br>"
                   "UBS disponíveis: %{customdata[2]}<extra></extra>"),
))
g1.update_layout(**base_layout(400, "Pressão sobre o SUS em cada região"))
g1.update_xaxes(range=[0, 115], gridcolor=PAL["border"])
g1.update_yaxes(gridcolor=PAL["border"])

# G2: Habitantes por UBS
df_hab = df_indic.sort_values("hab_por_ubs", ascending=True)
g2 = go.Figure(go.Bar(
    x=df_hab["hab_por_ubs"], y=df_hab["regiao"], orientation="h",
    marker=dict(color=[CORES_NIVEL[n] for n in df_hab["nivel"]],
                line=dict(width=0)),
    text=df_hab["hab_por_ubs"].apply(
        lambda v: f"{v:,.0f}".replace(",", ".") + " pessoas"),
    textposition="outside",
    textfont=dict(color=PAL["text"], size=11),
    hovertemplate="<b>%{y}</b><br>%{x:,.0f} pessoas por UBS<extra></extra>",
))
g2.add_vline(x=5000, line_dash="dash", line_color=PAL["ok"], line_width=1,
             opacity=0.4, annotation_text="Recomendado MS",
             annotation_font_color=PAL["ok"])
g2.update_layout(**base_layout(400, "Quantas pessoas cada UBS precisa atender"))
g2.update_xaxes(gridcolor=PAL["border"])
g2.update_yaxes(gridcolor=PAL["border"])

# G3: Hospitais SUS vs Privados
hosp_df = df_estab[df_estab["categoria"] == "Hospital"].copy()
hosp_count = hosp_df.groupby(["regiao", "is_sus"]).size().reset_index(name="n")

g3 = go.Figure()
for is_sus_val, tipo, cor in [(True, "Hospital SUS", PAL["hospital"]),
                               (False, "Hospital Privado", PAL["hospital_pv"])]:
    sub = hosp_count[hosp_count["is_sus"] == is_sus_val]
    sub_completo = df_indic[["regiao"]].merge(sub, on="regiao",
                                              how="left").fillna(0)
    g3.add_bar(
        name=tipo, x=sub_completo["regiao"], y=sub_completo["n"],
        marker_color=cor,
        text=sub_completo["n"].astype(int),
        textposition="inside",
        textfont=dict(color="white", size=12),
    )
g3.update_layout(**base_layout(360, "Hospitais por região: SUS × particular"))
g3.update_layout(barmode="stack",
                 legend=dict(orientation="h", y=-0.18, x=0.5,
                             xanchor="center", bgcolor="rgba(0,0,0,0)"))
g3.update_xaxes(gridcolor=PAL["border"])
g3.update_yaxes(gridcolor=PAL["border"], title="Quantidade")

# G4: Donut SUS
contagem = df_sus["categoria"].value_counts()
g4 = go.Figure(go.Pie(
    labels=contagem.index, values=contagem.values, hole=0.65,
    marker=dict(colors=[PAL["ubs"], PAL["hospital"], PAL["upa"]],
                line=dict(color=PAL["bg"], width=3)),
    textinfo="label+value",
    textfont=dict(color="white", size=12),
    hovertemplate="<b>%{label}</b><br>%{value} unidades<br>%{percent}<extra></extra>",
))
g4.update_layout(**base_layout(360,
    f"A rede pública SUS em números ({len(df_sus)} unidades)"))
g4.update_layout(showlegend=False, annotations=[dict(
    text=f"<b style='color:{PAL['text']};font-size:24px;'>{len(df_sus)}</b>"
         f"<br><span style='color:{PAL['text_dim']};font-size:11px;'>"
         f"unidades SUS</span>",
    x=0.5, y=0.5, font_size=14, showarrow=False)])


# G5: Radar — perfil de cada região
def normalize_serie(s, invert=False):
    mn, mx = s.min(), s.max()
    if mx == mn: return [50] * len(s)
    norm = (s - mn) / (mx - mn) * 100
    return (100 - norm) if invert else norm

df_radar = df_indic.copy()
df_radar["pop_norm"] = normalize_serie(df_radar["populacao"])
df_radar["ubs_norm"] = normalize_serie(df_radar["UBS"])
df_radar["hosp_norm"] = normalize_serie(df_radar["Hospital"])
df_radar["upa_norm"] = normalize_serie(df_radar["UPA"])
df_radar["cob_norm"] = normalize_serie(df_radar["hab_por_ubs"], invert=True)

eixos = ["População", "UBS", "Hospitais", "UPAs", "Cobertura UBS"]
cores_radar = [PAL["primary"], PAL["accent"], PAL["warn"],
               PAL["crit"], "#A78BFA"]
g5 = go.Figure()
for i, (_, r) in enumerate(df_radar.iterrows()):
    valores = [r["pop_norm"], r["ubs_norm"], r["hosp_norm"],
               r["upa_norm"], r["cob_norm"]]
    g5.add_trace(go.Scatterpolar(
        r=valores + [valores[0]],
        theta=eixos + [eixos[0]],
        name=r["regiao"],
        line=dict(color=cores_radar[i % len(cores_radar)], width=2.5),
        fill="toself", fillcolor=cores_radar[i % len(cores_radar)],
        opacity=0.18,
        hovertemplate=f"<b>{r['regiao']}</b><br>%{{theta}}: %{{r:.0f}}/100<extra></extra>",
    ))
g5.update_layout(
    title=dict(text="<b>Comparação entre as 5 regiões</b>",
               font=dict(color=PAL["text"], size=14, family="Inter")),
    polar=dict(
        bgcolor=PAL["bg_elevated"],
        radialaxis=dict(visible=True, range=[0, 100],
                        gridcolor=PAL["border"],
                        tickfont=dict(color=PAL["text_muted"], size=10)),
        angularaxis=dict(gridcolor=PAL["border"],
                         tickfont=dict(color=PAL["text"], size=13)),
    ),
    height=520, template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color=PAL["text_dim"]),
    margin=dict(l=80, r=80, t=80, b=80),
    legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center",
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=PAL["text"], size=12)),
)


# ─── 5. GRAFO NETWORKX CLÁSSICO (nós + arestas) ──────────────────────
G = nx.Graph()

for _, r in df_indic.iterrows():
    G.add_node(f"REG::{r['regiao']}", tipo="regiao", label=r["regiao"],
               pop=int(r["populacao"]), nivel=r["nivel"])

for _, e in df_sus.iterrows():
    nid = f"EST::{e['codigo_cnes']}"
    G.add_node(nid, tipo=e["categoria"],
               label=str(e["nome"])[:40], regiao=e["regiao"])
    G.add_edge(f"REG::{e['regiao']}", nid)

# Layout força (Fruchterman-Reingold) — espalha os nós
pos = nx.spring_layout(G, k=1.2, iterations=80, seed=42)

edge_x, edge_y = [], []
for a, b in G.edges():
    edge_x += [pos[a][0], pos[b][0], None]
    edge_y += [pos[a][1], pos[b][1], None]

g6 = go.Figure()
g6.add_scatter(x=edge_x, y=edge_y, mode="lines",
               line=dict(width=0.5, color=PAL["text_muted"]),
               opacity=0.4, hoverinfo="none", showlegend=False)

config_no = {
    "regiao":   {"cor": PAL["primary"],  "size": 38, "nome": "Região"},
    "UBS":      {"cor": PAL["ubs"],      "size": 9,  "nome": "UBS"},
    "Hospital": {"cor": PAL["hospital"], "size": 16, "nome": "Hospital"},
    "UPA":      {"cor": PAL["upa"],      "size": 13, "nome": "UPA"},
}

for tipo, cfg in config_no.items():
    nodes = [n for n, d in G.nodes(data=True) if d["tipo"] == tipo]
    if not nodes:
        continue
    nx_, ny_, txt = [], [], []
    for n in nodes:
        nx_.append(pos[n][0])
        ny_.append(pos[n][1])
        d = G.nodes[n]
        if tipo == "regiao":
            txt.append(f"<b>{d['label']}</b><br>"
                       f"População: {d['pop']:,}<br>"
                       f"Situação: {d['nivel']}")
        else:
            txt.append(f"<b>{d['label']}</b><br>{tipo} - {d['regiao']}")

    if tipo == "regiao":
        text_labels = [G.nodes[n]["label"] for n in nodes]
        textfont = dict(color="white", size=11, family="Inter")
        mode = "markers+text"
        g6.add_scatter(
            x=nx_, y=ny_, mode=mode, name=cfg["nome"],
            marker=dict(size=cfg["size"], color=cfg["cor"],
                        line=dict(width=2, color=PAL["bg"])),
            text=text_labels, hovertext=txt, hoverinfo="text",
            textfont=textfont, textposition="middle center",
        )
    else:
        g6.add_scatter(
            x=nx_, y=ny_, mode="markers", name=cfg["nome"],
            marker=dict(size=cfg["size"], color=cfg["cor"],
                        line=dict(width=2, color=PAL["bg"])),
            text=txt, hoverinfo="text",
        )

g6.update_layout(
    title=dict(text="<b>Rede de saúde pública: cada ponto é uma unidade</b>",
               font=dict(color=PAL["text"], size=14, family="Inter")),
    height=620, template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    xaxis=dict(visible=False, range=[-1.3, 1.3]),
    yaxis=dict(visible=False, range=[-1.3, 1.3]),
    margin=dict(l=20, r=20, t=60, b=20),
    legend=dict(orientation="h", y=-0.03,
                font=dict(color=PAL["text"], size=11),
                bgcolor="rgba(0,0,0,0)"),
    showlegend=True,
)


# ─── 6. INSIGHTS PRA POPULAÇÃO ───────────────────────────────────────
top_critico = df_indic.nlargest(1, "pressao").iloc[0]
top_pop = df_indic.nlargest(1, "populacao").iloc[0]
pior_cob = df_indic.nlargest(1, "hab_por_ubs").iloc[0]
melhor_cob = df_indic[df_indic["UBS"] > 0].nsmallest(1, "hab_por_ubs").iloc[0]
mais_hosp = df_indic.nlargest(1, "Hospital").iloc[0]
n_alta = ((df_indic["nivel"] == "Crítico")
          | (df_indic["nivel"] == "Sobrecarga")).sum()

n_sus = len(df_sus)
n_hosp_sus = int(((df_estab["categoria"] == "Hospital")
                  & df_estab["is_sus"]).sum())
n_hosp_pv = int(((df_estab["categoria"] == "Hospital")
                 & ~df_estab["is_sus"]).sum())
pct_hosp_pv = (n_hosp_pv / (n_hosp_sus + n_hosp_pv) * 100
               if (n_hosp_sus + n_hosp_pv) > 0 else 0)


# ─── 7. RANKING ──────────────────────────────────────────────────────
def badge_nivel(n):
    cor = CORES_NIVEL[n]
    return (f'<span class="badge" style="background:{cor}1A;color:{cor};'
            f'border-color:{cor}66;">{n}</span>')

ranking_rows = ""
for _, r in df_indic.sort_values("pressao", ascending=False).iterrows():
    cor = CORES_NIVEL[r["nivel"]]
    ranking_rows += f"""
    <tr>
      <td><b>{r['regiao']}</b></td>
      <td>{r['populacao']:,}</td>
      <td>{int(r['UBS'])}</td>
      <td>{int(r['Hospital'])}</td>
      <td>{int(r['UPA'])}</td>
      <td>{r['hab_por_ubs']:,.0f}</td>
      <td>
        <div class="score-bar-wrap">
          <div class="score-bar" style="width:{r['pressao']}%;background:{cor};"></div>
          <span class="score-val">{r['pressao']:.0f}</span>
        </div>
      </td>
      <td>{badge_nivel(r['nivel'])}</td>
    </tr>"""


# ─── 8. MARKERS PRO MAPA LEAFLET ─────────────────────────────────────
markers_data = []
for _, e in df_sus.iterrows():
    markers_data.append({
        "lat":       float(e["latitude"]),
        "lng":       float(e["longitude"]),
        "nome":      str(e["nome"])[:60].replace("'", "&#39;"),
        "categoria": e["categoria"],
        "regiao":    e["regiao"],
    })
markers_json = json.dumps(markers_data, ensure_ascii=False)


# ─── 9. MONTAGEM HTML ────────────────────────────────────────────────
def to_div(fig, did):
    return fig.to_html(include_plotlyjs=False, full_html=False, div_id=did,
                       config={"displayModeBar": False, "responsive": True})

CSS = """
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0A0E1A; --bg-card: #131929; --bg-elev: #1A2238;
    --border: #1E2A45; --border-strong: #2A3656;
    --text: #E5EEFF; --text-dim: #8B95B7; --text-muted: #5B6584;
    --primary: #5B8DEF; --accent: #00D4AA;
    --warn: #FFB547; --crit: #FF5C7C; --ok: #00D4AA;
    --shadow-md: 0 4px 16px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.4);
  }
  body {
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.6;
    -webkit-font-smoothing: antialiased; min-height: 100vh;
  }
  body::before {
    content: ''; position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background:
      radial-gradient(circle at 15% 0%, rgba(91,141,239,0.08), transparent 50%),
      radial-gradient(circle at 85% 100%, rgba(0,212,170,0.06), transparent 50%);
  }
  .container { max-width: 1500px; margin: 0 auto; padding: 32px 24px; position: relative; z-index: 1; }
  header.hero {
    background: linear-gradient(135deg, #0F1530 0%, #0A0E1A 100%);
    border-bottom: 1px solid var(--border); padding: 36px 24px 44px;
    position: relative; overflow: hidden;
  }
  header.hero::after {
    content: ''; position: absolute; top: 0; right: 0; width: 60%; height: 100%;
    background: radial-gradient(ellipse at top right, rgba(91,141,239,0.15), transparent 60%);
    pointer-events: none;
  }
  .hero-content { max-width: 1500px; margin: 0 auto; position: relative; z-index: 1; }
  .pill {
    display: inline-flex; align-items: center; gap: 6px;
    background: rgba(91,141,239,0.1); color: var(--primary);
    padding: 4px 12px; border-radius: 100px; font-size: 11px;
    letter-spacing: 1.5px; text-transform: uppercase; font-weight: 600;
    border: 1px solid rgba(91,141,239,0.25); margin-bottom: 16px;
  }
  .pill::before {
    content: ''; width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent); box-shadow: 0 0 8px var(--accent);
    animation: pulse 2s infinite;
  }
  @keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(0.85); } }
  header.hero h1 {
    font-size: 38px; font-weight: 800; letter-spacing: -0.8px;
    line-height: 1.1; margin-bottom: 14px;
    background: linear-gradient(135deg, #E5EEFF 0%, #8B95B7 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  header.hero .subtitle { font-size: 17px; color: var(--text-dim); max-width: 780px; margin-bottom: 20px; }
  .meta { display: flex; gap: 24px; flex-wrap: wrap; font-size: 12px; color: var(--text-muted); }
  .meta span { display: flex; align-items: center; gap: 6px; }
  .meta .dot { width: 4px; height: 4px; border-radius: 50%; background: var(--text-muted); }
  .como-ler {
    background: linear-gradient(135deg, rgba(91,141,239,0.10), rgba(0,212,170,0.04));
    border: 1px solid rgba(91,141,239,0.25);
    border-radius: 14px; padding: 20px 24px; margin: 28px 0;
    display: grid; grid-template-columns: auto 1fr; gap: 18px; align-items: start;
  }
  .como-ler-icon { font-size: 28px; }
  .como-ler h3 { color: var(--text); font-size: 16px; font-weight: 700; margin-bottom: 8px; }
  .como-ler p { color: var(--text-dim); font-size: 14px; }
  .como-ler ul { list-style: none; padding: 0; margin-top: 6px; }
  .como-ler li { color: var(--text-dim); font-size: 13px; padding: 4px 0; display: flex; gap: 8px; }
  .como-ler li::before { content: '•'; color: var(--primary); font-weight: 700; }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 12px; margin: 24px 0 36px; }
  .kpi {
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: 12px; padding: 18px 20px;
    transition: all 0.3s; position: relative; overflow: hidden;
  }
  .kpi::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 2px; background: var(--primary); opacity: 0.6; }
  .kpi.crit::before { background: var(--crit); }
  .kpi.ok::before { background: var(--ok); }
  .kpi.warn::before { background: var(--warn); }
  .kpi:hover { transform: translateY(-2px); border-color: var(--border-strong); box-shadow: var(--shadow-md); }
  .kpi-val { font-size: 24px; font-weight: 800; color: var(--text); letter-spacing: -0.5px; line-height: 1; font-variant-numeric: tabular-nums; }
  .kpi.crit .kpi-val { color: var(--crit); } .kpi.ok .kpi-val { color: var(--ok); } .kpi.warn .kpi-val { color: var(--warn); }
  .kpi-lbl { font-size: 10px; color: var(--text-muted); margin-top: 6px; text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
  section { margin-top: 52px; }
  .section-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 20px; }
  .section-head h2 { font-size: 22px; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }
  .section-head .num { color: var(--primary); margin-right: 10px; font-weight: 800; }
  .section-head .desc { font-size: 13px; color: var(--text-muted); }
  .insight {
    background: linear-gradient(135deg, rgba(91,141,239,0.06), rgba(0,212,170,0.04));
    border: 1px solid var(--border); border-left: 3px solid var(--primary);
    padding: 16px 20px; border-radius: 10px; margin-bottom: 20px;
    font-size: 14px; line-height: 1.65; color: var(--text-dim);
  }
  .insight b { color: var(--text); }
  .insight.crit { border-left-color: var(--crit); background: linear-gradient(135deg, rgba(255,92,124,0.08), transparent); }
  .grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
  @media (max-width: 1100px) { .grid { grid-template-columns: 1fr; } }
  .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 14px; transition: all 0.3s; }
  .card:hover { border-color: var(--border-strong); box-shadow: var(--shadow-md); }
  .card.full { grid-column: 1 / -1; }
  .ranking { background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 22px; overflow-x: auto; }
  .ranking table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .ranking th { text-align: left; padding: 12px 14px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-size: 10px; letter-spacing: 1px; border-bottom: 1px solid var(--border); }
  .ranking td { padding: 16px 14px; border-bottom: 1px solid var(--border); color: var(--text-dim); font-variant-numeric: tabular-nums; }
  .ranking tr:last-child td { border-bottom: none; }
  .ranking tr:hover { background: rgba(91,141,239,0.04); }
  .ranking td b { color: var(--text); }
  .score-bar-wrap { display: flex; align-items: center; gap: 10px; background: var(--bg-elev); border-radius: 100px; padding: 3px 4px; min-width: 140px; }
  .score-bar { height: 10px; border-radius: 100px; min-width: 10px; transition: width 0.5s; }
  .score-val { font-weight: 700; color: var(--text); font-size: 12px; padding-right: 8px; }
  .badge { display: inline-block; padding: 3px 10px; border-radius: 100px; font-size: 10px; font-weight: 700; letter-spacing: 0.5px; border: 1px solid; text-transform: uppercase; }
  #mapa-leaflet { height: 540px; border-radius: 14px; overflow: hidden; border: 1px solid var(--border); box-shadow: var(--shadow-md); }
  .leaflet-popup-content-wrapper { background: var(--bg-card) !important; color: var(--text) !important; border-radius: 10px !important; padding: 4px !important; border: 1px solid var(--border) !important; }
  .leaflet-popup-tip { background: var(--bg-card) !important; }
  .leaflet-popup-content { margin: 12px 16px !important; font-family: Inter, sans-serif; font-size: 13px; }
  .leaflet-popup-content b { color: var(--primary); }
  .leaflet-popup-content .cat-tag { display: inline-block; padding: 2px 8px; border-radius: 100px; font-size: 10px; font-weight: 700; margin-top: 6px; }
  .leaflet-control-attribution { background: rgba(10,14,26,0.8) !important; color: var(--text-muted) !important; font-size: 10px !important; }
  .leaflet-control-attribution a { color: var(--primary) !important; }
  .map-legend { position: absolute; bottom: 16px; left: 16px; z-index: 1000; background: rgba(19,25,41,0.92); border: 1px solid var(--border); backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px); border-radius: 10px; padding: 12px 14px; font-size: 12px; }
  .map-legend-item { display: flex; align-items: center; gap: 8px; margin: 4px 0; color: var(--text-dim); }
  .map-legend-dot { width: 10px; height: 10px; border-radius: 50%; box-shadow: 0 0 0 2px rgba(10,14,26,0.6); }
  .conclusao { background: var(--bg-card); border: 1px solid var(--border); border-left: 3px solid var(--accent); border-radius: 10px; padding: 18px 22px; margin-bottom: 12px; font-size: 14px; line-height: 1.65; color: var(--text-dim); }
  .conclusao b { color: var(--text); }
  footer { margin-top: 64px; padding: 32px 24px; border-top: 1px solid var(--border); text-align: center; font-size: 12px; color: var(--text-muted); }
  footer p { margin-bottom: 6px; }
  footer strong { color: var(--text-dim); }
</style>
"""

html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Saúde Pública em Campinas — Painel para o Cidadão</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
{CSS}
</head>
<body>

<header class="hero">
  <div class="hero-content">
    <div class="pill">Painel da Saúde Pública · Campinas/SP</div>
    <h1>A saúde pública<br>chega a todo mundo?</h1>
    <p class="subtitle">
      Este painel mostra, com dados oficiais e atualizados, como a rede do SUS
      está distribuída entre as 5 regiões de Campinas — e em quais lugares
      o atendimento está mais sobrecarregado.
    </p>
    <div class="meta">
      <span>📍 Campinas/SP</span>
      <span class="dot"></span>
      <span>👥 1.139.047 moradores</span>
      <span class="dot"></span>
      <span>🏥 {len(df_sus)} unidades do SUS analisadas</span>
      <span class="dot"></span>
      <span>📅 Dados do Censo 2022</span>
    </div>
  </div>
</header>

<div class="container">

  <div class="como-ler">
    <div class="como-ler-icon">💡</div>
    <div>
      <h3>Como ler este painel</h3>
      <p style="margin-bottom:10px;">
        Tudo o que você vê aqui foi calculado a partir de dois bancos de dados
        públicos do governo: o <b>CNES</b> (lista oficial de hospitais e UBS) e o
        <b>Censo 2022 do IBGE</b> (número de moradores).
      </p>
      <ul>
        <li><b>UBS</b> = Unidade Básica de Saúde (postinho de bairro)</li>
        <li><b>UPA</b> = Unidade de Pronto Atendimento (24h, urgências)</li>
        <li><b>Pressão sobre o SUS</b> = nota de 0 (tranquilo) a 100 (crítico)
            que indica o quanto cada região está sobrecarregada</li>
        <li>O Ministério da Saúde recomenda <b>1 UBS para cada 3 a 5 mil pessoas</b></li>
      </ul>
    </div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="kpi-val">1.139.047</div>
      <div class="kpi-lbl">Moradores</div></div>
    <div class="kpi ok"><div class="kpi-val">{n_sus}</div>
      <div class="kpi-lbl">Unidades do SUS</div></div>
    <div class="kpi"><div class="kpi-val">{int(df_indic['UBS'].sum())}</div>
      <div class="kpi-lbl">UBS (postinhos)</div></div>
    <div class="kpi"><div class="kpi-val">{int(df_indic['Hospital'].sum())}</div>
      <div class="kpi-lbl">Hospitais SUS</div></div>
    <div class="kpi warn"><div class="kpi-val">{int(df_indic['UPA'].sum())}</div>
      <div class="kpi-lbl">UPAs (24h)</div></div>
    <div class="kpi crit"><div class="kpi-val">{df_indic[df_indic['UBS']>0]['hab_por_ubs'].median():,.0f}</div>
      <div class="kpi-lbl">Hab/UBS (mediana)</div></div>
    <div class="kpi crit"><div class="kpi-val">{n_alta}/5</div>
      <div class="kpi-lbl">Regiões sobrecarregadas</div></div>
  </div>

  <section>
    <div class="section-head">
      <h2><span class="num">01</span>Onde a saúde está mais sobrecarregada?</h2>
      <span class="desc">Termômetro da pressão sobre o SUS em cada região</span>
    </div>
    <div class="insight crit">
      A região <b>{top_critico['regiao']}</b> está com a maior pressão sobre
      a saúde pública — nota <b>{top_critico['pressao']:.0f}/100</b>, com
      <b>{top_critico['hab_por_ubs']:,.0f} moradores</b> dependendo de cada
      UBS. Isso é {top_critico['hab_por_ubs']/4000:.1f} vezes acima do que o
      Ministério da Saúde recomenda.
    </div>
    <div class="grid">
      <div class="card">{to_div(g1, "g1")}</div>
      <div class="card">{to_div(g2, "g2")}</div>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">02</span>Quadro completo por região</h2>
      <span class="desc">Tabela com todos os números importantes</span>
    </div>
    <div class="ranking">
      <table>
        <thead>
          <tr>
            <th>Região</th><th>Moradores</th><th>UBS</th><th>Hosp</th>
            <th>UPA</th><th>Pessoas/UBS</th><th>Pressão</th><th>Situação</th>
          </tr>
        </thead>
        <tbody>{ranking_rows}</tbody>
      </table>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">03</span>Hospitais: o que é SUS e o que é particular?</h2>
      <span class="desc">Quem depende do SUS conta só com os hospitais SUS</span>
    </div>
    <div class="insight">
      Em Campinas existem <b>{n_hosp_sus} hospitais que atendem pelo SUS</b>
      e <b>{n_hosp_pv} hospitais privados</b>. Como cerca de 7 em cada 10
      brasileiros dependem do SUS, o número total de hospitais não conta a
      história toda — o que importa é quantos atendem pelo SUS em cada região.
    </div>
    <div class="grid">
      <div class="card">{to_div(g3, "g3")}</div>
      <div class="card">{to_div(g4, "g4")}</div>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">04</span>Comparando as 5 regiões</h2>
      <span class="desc">Cada eixo mostra um aspecto: quanto maior, melhor (exceto população)</span>
    </div>
    <div class="insight">
      Cada região tem um perfil próprio. <b>{top_pop['regiao']}</b> tem a
      maior população, enquanto <b>{melhor_cob['regiao']}</b> tem a melhor
      cobertura de UBS por habitante. Compare visualmente abaixo.
    </div>
    <div class="card full">{to_div(g5, "g5")}</div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">05</span>Mapa da rede</h2>
      <span class="desc">Cada ponto colorido é uma unidade de saúde do SUS</span>
    </div>
    <div class="insight">
      Clique nos pontos do mapa pra ver detalhes de cada unidade. Use o
      zoom pra navegar pela cidade.
    </div>
    <div style="position:relative;">
      <div id="mapa-leaflet"></div>
      <div class="map-legend">
        <div style="font-weight:700;color:var(--text);margin-bottom:8px;font-size:11px;letter-spacing:1px;text-transform:uppercase;">Legenda</div>
        <div class="map-legend-item"><span class="map-legend-dot" style="background:#5B8DEF"></span>UBS</div>
        <div class="map-legend-item"><span class="map-legend-dot" style="background:#FF5C7C"></span>Hospital SUS</div>
        <div class="map-legend-item"><span class="map-legend-dot" style="background:#FFB547"></span>UPA</div>
      </div>
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">06</span>A rede como um grafo</h2>
      <span class="desc">Visualização em nós (unidades) e arestas (conexões)</span>
    </div>
    <div class="insight">
      Cada círculo grande no centro é uma das 5 regiões. Os círculos menores
      ao redor são as unidades de saúde ligadas àquela região. Regiões com
      mais "ramos" são as que têm mais unidades — mas atenção: <b>quantidade
      não é a mesma coisa que cobertura</b>, já que cada região tem uma
      população diferente.
    </div>
    <div class="card full">{to_div(g6, "g6")}</div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">07</span>O que isso tudo significa?</h2>
      <span class="desc">Os principais achados em linguagem direta</span>
    </div>
    <div class="conclusao">
      <b>1. A saúde básica está sobrecarregada em toda a cidade.</b>
      Em Campinas, na média, <b>cada UBS atende
      {df_indic[df_indic['UBS']>0]['hab_por_ubs'].median():,.0f} moradores</b> —
      o Ministério da Saúde recomenda no máximo 5.000. Estamos
      {df_indic[df_indic['UBS']>0]['hab_por_ubs'].median()/4000:.1f}×
      acima do ideal.
    </div>
    <div class="conclusao">
      <b>2. Há diferença grande entre as regiões.</b> Na região
      {pior_cob['regiao']}, cada UBS atende {pior_cob['hab_por_ubs']:,.0f}
      pessoas. Na região {melhor_cob['regiao']}, esse número cai pra
      {melhor_cob['hab_por_ubs']:,.0f}. Quem mora numa região está em
      situação muito pior do que quem mora em outra.
    </div>
    <div class="conclusao">
      <b>3. Os hospitais SUS ficam concentrados no centro.</b> A região
      {mais_hosp['regiao']} tem {int(mais_hosp['Hospital'])} hospitais SUS.
      Quem mora em bairros mais afastados precisa se deslocar — e isso
      afeta o acesso, especialmente em emergências.
    </div>
    <div class="conclusao">
      <b>4. A rede privada é grande, mas não muda a equação do SUS.</b>
      Os {n_hosp_pv} hospitais privados ({pct_hosp_pv:.0f}% do total) só
      atendem quem tem plano de saúde ou pode pagar. Pra quem depende do
      SUS, só os {n_hosp_sus} hospitais públicos contam.
    </div>
    <div class="conclusao">
      <b>5. A {top_critico['regiao']} precisa de atenção prioritária.</b>
      Com a pior nota de pressão da cidade ({top_critico['pressao']:.0f}/100),
      essa região deveria ser prioridade para novas UBS — em linha com a
      Meta 3.8 do ODS 3 da ONU, que pede cobertura universal de saúde.
    </div>
  </section>

  <section>
    <div class="section-head">
      <h2><span class="num">08</span>De onde vieram esses dados?</h2>
      <span class="desc">Transparência sobre fontes e limites do painel</span>
    </div>
    <div class="insight">
      <b>Fontes oficiais:</b><br>
      • <b>Hospitais e UBS:</b> CNES (Cadastro Nacional de Estabelecimentos
      de Saúde do Ministério da Saúde, via API DEMAS)<br>
      • <b>População:</b> Censo 2022 do IBGE, tabela 4709<br><br>
      Os dados foram armazenados no MongoDB Atlas, com 3 coleções e
      11 índices. A análise foi feita em Python, usando pandas, plotly,
      networkx e leaflet.
    </div>
    <div class="insight" style="border-left-color: var(--warn); background: linear-gradient(135deg, rgba(255,181,71,0.06), transparent);">
      <b>Importante saber:</b><br>
      • A divisão da cidade em 5 regiões (Norte, Sul, Leste, Sudoeste,
      Noroeste) segue o desenho da Secretaria Municipal de Saúde.<br>
      • Como o IBGE não publica número exato de habitantes por essa
      divisão, a população por região é uma <b>estimativa proporcional</b>
      baseada na distribuição populacional da cidade. O número total
      (1.139.047) é o oficial do Censo.<br>
      • Removemos do painel {len(df_ruido)} unidades do CNES classificadas
      como UBS/UPA mas que não atendem o público geral (penitenciárias e
      clínicas particulares mal classificadas).
    </div>
  </section>

</div>

<footer>
  <p><strong>Fontes:</strong> CNES/DataSUS · IBGE Censo 2022 · SMS Campinas</p>
  <p><strong>Tecnologias:</strong> Python · MongoDB Atlas · Plotly · NetworkX · Leaflet</p>
  <p>Arthur Costa Marques · Conrado Marques · Fábio Barbosa Gonsalez · Patrick Rovaron Franco</p>
  <p style="margin-top:12px;opacity:0.5;font-size:11px;">
    Projeto Integrador · Bancos de Dados Não Relacionais · PUC-Campinas · 2026
  </p>
</footer>

<script>
const markers = {markers_json};
const map = L.map('mapa-leaflet', {{ zoomControl: true, attributionControl: true }})
              .setView([-22.9056, -47.0608], 11);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '© OpenStreetMap · © CARTO', subdomains: 'abcd', maxZoom: 20,
}}).addTo(map);
const CORES = {{ 'UBS': '#5B8DEF', 'Hospital': '#FF5C7C', 'UPA': '#FFB547' }};
markers.forEach(m => {{
  const cor = CORES[m.categoria] || '#8B95B7';
  const marker = L.circleMarker([m.lat, m.lng], {{
    radius: m.categoria === 'Hospital' ? 9 : (m.categoria === 'UPA' ? 8 : 6),
    fillColor: cor, color: '#0A0E1A', weight: 1.5, opacity: 1, fillOpacity: 0.85,
  }}).addTo(map);
  marker.bindPopup(`
    <b>${{m.nome}}</b><br>
    <span style="color:#8B95B7;font-size:12px;">${{m.regiao}}</span>
    <div class="cat-tag" style="background:${{cor}}26;color:${{cor}};">${{m.categoria}}</div>
  `);
}});
if (markers.length > 0) {{
  const bounds = markers.map(m => [m.lat, m.lng]);
  map.fitBounds(bounds, {{padding: [40, 40], maxZoom: 12}});
}}
</script>

</body>
</html>"""

OUT = Path(os.environ.get(
    "DASHBOARD_SAIDA",
    loader.RAIZ / "build" / "dashboard_gerado.html"))
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print(f"\n✓ Dashboard v4 salvo: {OUT}")
print(f"  Tamanho: {OUT.stat().st_size:,} bytes")