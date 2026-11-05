# Mapa de Acesso à Saúde Pública em Campinas

Projeto Integrador da disciplina **Bancos de Dados Não Relacionais**, PUC-Campinas, 2026. Trabalho acadêmico em grupo, feito com dados públicos.

## Resumo

Painel que cruza o cadastro de UBS, hospitais e UPAs de Campinas (CNES, Ministério da Saúde) com a população do Censo 2022 (IBGE) para comparar a razão habitantes por UBS entre os 5 distritos de saúde da cidade. Os dados tratados foram modelados em documentos JSON e carregados no MongoDB Atlas; o painel é um HTML com gráficos, um grafo e um mapa.

## Problema

A rede pública de saúde de Campinas está distribuída de forma desigual entre os distritos? Responder isso exige juntar duas fontes que não conversam entre si (cadastro de estabelecimentos e população) e agrupá-las numa divisão geográfica que o IBGE não publica.

## Objetivo

Montar o caminho completo, da coleta em fontes públicas até uma visualização, usando um banco orientado a documentos (MongoDB), e apresentar os indicadores por distrito de forma legível para quem não é da área.

## Arquitetura

```mermaid
flowchart LR
    A["CNES / SIDRA<br/>(fontes públicas)"] --> B["Tratamento<br/>(Python, pandas)"]
    B --> C["JSON<br/>data/*.json"]
    C --> D[("MongoDB Atlas<br/>saude_campinas")]
    D --> E["Leitura<br/>src/loader.py"]
    C -.->|"modo local (padrão)"| E
    E --> F["Dashboard<br/>src/dashboard.py"]
    F --> G["docs/index.html"]
```

As etapas de coleta, tratamento e carga no Atlas (`src/pipeline.py`) são **registro histórico**. O fluxo reproduzível deste repositório parte dos JSONs em `data/`. Detalhes em [docs/arquitetura.md](docs/arquitetura.md).

## Tecnologias

Python, pandas, MongoDB Atlas (pymongo), Plotly, NetworkX, Leaflet. O notebook foi escrito para Jupyter/Colab.

## Instalação

Testado com Python 3.11 no Windows.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Para executar o notebook (opcional): `pip install -r requirements-dev.txt`.

## Execução

### Modo local (padrão, sem internet para os dados e sem credenciais)

```bash
python src/loader.py        # confere a leitura de data/*.json
python src/dashboard.py     # gera build/dashboard_gerado.html
```

O notebook [notebooks/proj_integrador.ipynb](notebooks/proj_integrador.ipynb) faz o mesmo passo a passo (dados, tabelas, dashboard) e tem as saídas salvas. Defina `DASHBOARD_SAIDA` para mudar o arquivo de saída do gerador.

### Modo Atlas (opcional, só leitura)

Defina `MONGO_URI` no ambiente (modelo em [.env.example](.env.example)); o `loader.py` passa a ler do banco `saude_campinas` (coleções `regioes`, `estabelecimentos`, `relacoes`).

```bash
export MONGO_URI="mongodb+srv://USUARIO:SENHA@SEU_CLUSTER.mongodb.net/"
python src/dashboard.py
```

Nunca versione um `.env` com valor real. Este caminho **não foi testado** nesta versão do repositório (nenhuma conexão ao Atlas foi feita).

A Etapa 4 do pipeline histórico (`etapa_4_carregar_no_atlas`) apaga (`drop`) as três coleções antes de recarregá-las. Ela fica desativada por padrão e só executa com `confirmar_sobrescrita=True`.

## Prints

Prints do dashboard (`docs/img/`), gerados a 1440 px de largura:

| | |
|---|---|
| ![Topo e indicadores](docs/img/01-topo-kpis.png) | ![Pressão por região](docs/img/02-pressao-regioes.png) |
| ![Quadro por região](docs/img/03-quadro-regioes.png) | ![Hospitais SUS e particulares](docs/img/04-hospitais.png) |
| ![Comparação entre regiões](docs/img/05-comparacao-radar.png) | ![Grafo da rede](docs/img/07-grafo.png) |

O print do mapa não está aqui: ao gerar os prints, os tiles do mapa-base (CARTO `dark_all`) vieram com a marca d'água "API KEY REQUIRED". Ver Limitações.

## Dashboard

Link (GitHub Pages): **PREENCHER-APÓS-ATIVAR** (a ser ativado depois da confirmação do grupo e da docente).

O arquivo publicado é [docs/index.html](docs/index.html).

## Fontes dos dados

- **Estabelecimentos:** CNES, API DEMAS do Ministério da Saúde (`apidadosabertos.saude.gov.br`), município de Campinas.
- **População:** IBGE, SIDRA, tabela 4709, Censo 2022.

Os dados são públicos. O recorte tratado (115 estabelecimentos) está em `data/`.

## Autores e docente

- Arthur Costa Marques
- Conrado Marques
- Fábio Barbosa Gonsalez
- Patrick Rovaron Franco

Docente: Joice Marin.

## Contribuições por pessoa

A divisão individual de tarefas ainda não foi informada pelo grupo. Até lá, todas as etapas constam como **desenvolvido em grupo**:

| Etapa | Autoria |
|---|---|
| Coleta CNES/IBGE | desenvolvido em grupo |
| Tratamento | desenvolvido em grupo |
| Modelagem MongoDB | desenvolvido em grupo |
| Carga no Atlas | desenvolvido em grupo |
| Leitura | desenvolvido em grupo |
| Dashboard / mapa | desenvolvido em grupo |
| Apresentação | desenvolvido em grupo |
| Reorganização do repositório para publicação | a definir |

## Licença

Código sob licença MIT, **proposta e pendente de confirmação do grupo** (ver [LICENSE](LICENSE)). Os dados vêm de fontes públicas (CNES e IBGE) e devem ser citados conforme a seção acima.

## Status: o que está implementado, testado e medido

- **Implementado e testado (modo local):** leitura de `data/*.json` (115 estabelecimentos, 5 regiões, 115 relações); filtro do dashboard (91 unidades SUS: 70 UBS, 16 hospitais, 5 UPAs; 5 removidas: 3 UBS e 2 UPAs não-SUS); geração do dashboard; execução do notebook de ponta a ponta. Testado em ambiente virtual novo, instalando só `requirements.txt`.
- **Implementado, não testado:** modo Atlas (`MONGO_URI`); etapas 1 a 4 do pipeline (código preservado, nenhuma chamada às APIs ou ao Atlas foi feita ao preparar este repositório).
- **Medido:** nada além das contagens acima. Não há avaliação de desempenho, de qualidade dos dados nem validação dos indicadores contra fontes oficiais por distrito.

## Limitações conhecidas

**Sobre os dados e a metodologia**

- A **população por região é uma estimativa proporcional** (`PROPORCOES_SMS`) aplicada ao total do Censo 2022. O IBGE não publica população por distrito de saúde. Todos os valores de "habitantes por UBS" dependem dessa premissa.
- O **NOROESTE tem apenas 4 bairros** no mapeamento bairro → distrito, o que resulta em 2 UBS e cerca de 87 mil habitantes por UBS. É provável que isso seja um artefato do mapeamento, e não um achado.
- Os **centroides dos distritos são aproximados**, e o mapeamento bairro → distrito foi feito por correspondência de texto (inclui "contém"), sujeita a erro.
- **24 dos 115 estabelecimentos** (19 hospitais privados e 5 UBS/UPA não-SUS) não entram nos indicadores do SUS.
- Os indicadores gravados em `data/regioes.json` contam todas as UBS (inclusive não-SUS); o dashboard recalcula só com SUS. Por isso os valores de hab/UBS diferem entre o JSON e o dashboard (ex.: LESTE, 10.197 no JSON e 10.707 no dashboard).
- Os números **4.925** (registros brutos do CNES) e **1.139.047** (população do Censo) vêm de comentários do código e do HTML. Constam aqui **conforme o registro do pipeline**, sem reverificação.
- As etapas 1 a 4 são registro histórico: refazer a coleta pode dar números diferentes, porque CNES e IBGE mudam.

**Sobre o dashboard (`docs/index.html`, mantido como entregue)**

- **Divisor inconsistente:** o texto diz que o Ministério da Saúde recomenda "no máximo 5.000" habitantes por UBS, mas o cálculo de "X vezes acima do recomendado" divide por 4.000. Com 5.000, o NOROESTE seria 17,4 vezes (o painel mostra 21,8) e a mediana 2,9 vezes (o painel mostra 3,6). Não foi corrigido nesta versão.
- A **conclusão 3** ("hospitais SUS concentrados no centro") é texto fixo, não resultado calculado. Nos dados, os hospitais SUS por região são SUL 6, NORTE 4 e LESTE 4; contando também os privados, NORTE 13 e LESTE 12. O texto não deve ser lido como resultado verificado.
- O texto sobre as 5 unidades removidas ("penitenciárias e clínicas particulares") não foi verificado: pelos nomes, só 2 são penitenciária/detenção.
- Frases como "7 em cada 10 brasileiros dependem do SUS" e a faixa recomendada de "1 UBS para cada 3 a 5 mil pessoas" não têm fonte citada no painel.
- O painel cita uma **contagem de índices do MongoDB** que não corresponde aos 7 índices criados explicitamente no código (o número real no Atlas não foi verificado).
- Formatação mista de números: alguns usam vírgula como separador de milhar (ex.: "14,428") e outros ponto (ex.: "5.000").
- No grafo, os rótulos NORTE e SUDOESTE se sobrepõem.
- O painel **depende de CDNs** (Plotly, Leaflet, Google Fonts, tiles CARTO) e precisa de internet.
- **Mapa-base:** nos testes feitos ao preparar este repositório, os tiles do CARTO (`dark_all`) retornaram a imagem "API KEY REQUIRED" no lugar do mapa; os pontos das unidades aparecem, mas sem o mapa de fundo. Não foi investigada a causa nem foi feita correção.
