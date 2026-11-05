(function () {
  'use strict';

  var dados = JSON.parse(document.getElementById('dados-painel').textContent);
  var POR_PAGINA = 12;

  function $(id) { return document.getElementById(id); }
  function normalizar(texto) {
    return String(texto).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  }
  function cor(nome) {
    return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  }
  function temaAtual() { return document.documentElement.getAttribute('data-tema'); }

  // ─── Gráficos ───────────────────────────────────────────────────────
  // O Plotly é 3/4 do arquivo e travava a abertura. Ele fica guardado como texto e só é
  // executado quando o primeiro gráfico está para aparecer; cada gráfico é desenhado uma vez.
  var desenhados = {};

  function estiloTema() {
    var texto = cor('--texto2');
    var grade = cor('--grade-graf');
    return {
      'font.color': texto,
      'xaxis.gridcolor': grade, 'yaxis.gridcolor': grade,
      'xaxis.zerolinecolor': grade, 'yaxis.zerolinecolor': grade,
      'xaxis.linecolor': grade, 'yaxis.linecolor': grade
    };
  }

  function carregarPlotly() {
    var guardado = $('js-plotly');
    if (window.Plotly || !guardado) return;
    var script = document.createElement('script');
    script.text = guardado.textContent;
    document.head.appendChild(script);
    guardado.remove();
  }

  function comEstiloTema(layout) {
    var estilo = estiloTema();
    Object.keys(estilo).forEach(function (chave) {
      var partes = chave.split('.');
      layout[partes[0]] = layout[partes[0]] || {};
      layout[partes[0]][partes[1]] = estilo[chave];
    });
    return layout;
  }

  function avisarFalhaGrafico(alvo) {
    var aviso = document.createElement('p');
    aviso.className = 'grafico-erro';
    aviso.textContent = 'Não foi possível desenhar este gráfico neste navegador. Os mesmos números estão no quadro por distrito.';
    alvo.appendChild(aviso);
  }

  function desenharGrafico(id) {
    if (desenhados[id]) return;
    desenhados[id] = true;
    var alvo = $(id);
    var figura = dados.figuras[id];
    try {
      carregarPlotly();
      window.Plotly.newPlot(alvo, figura.data, comEstiloTema(figura.layout), {
        displayModeBar: false, responsive: true, locale: 'pt-BR'
      });
    } catch (erro) {
      delete desenhados[id];
      avisarFalhaGrafico(alvo);
    }
  }

  function iniciarGraficos() {
    var ids = Object.keys(dados.figuras).filter(function (id) { return $(id); });
    function desenharTodos() { ids.forEach(desenharGrafico); }
    // Para quem imprime sem ter rolado até os gráficos.
    window.addEventListener('beforeprint', desenharTodos);
    ids.forEach(function (id) {
      // Reserva a altura final: a página não muda de tamanho quando o gráfico aparece.
      $(id).style.minHeight = dados.figuras[id].layout.height + 'px';
    });
    if (!window.IntersectionObserver) {
      desenharTodos();
      return;
    }
    var observador = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (entrada) {
        if (!entrada.isIntersecting) return;
        observador.unobserve(entrada.target);
        // Uma tarefa por gráfico, para a rolagem e a digitação não esperarem o conjunto.
        setTimeout(function () { desenharGrafico(entrada.target.id); }, 0);
      });
    }, { rootMargin: '800px 0px' });
    ids.forEach(function (id) { observador.observe($(id)); });
  }

  // ─── Tema ───────────────────────────────────────────────────────────
  function rotuloTema() {
    $('alternar-tema').textContent = temaAtual() === 'claro' ? 'Tema escuro' : 'Tema claro';
  }

  function aplicarTema(tema) {
    document.documentElement.setAttribute('data-tema', tema);
    try { localStorage.setItem('tema', tema); } catch (erro) { /* navegação privada */ }
    rotuloTema();
    Object.keys(desenhados).forEach(function (id) { window.Plotly.relayout($(id), estiloTema()); });
  }

  var botaoTema = $('alternar-tema');
  botaoTema.hidden = false;
  rotuloTema();
  botaoTema.addEventListener('click', function () {
    aplicarTema(temaAtual() === 'claro' ? 'escuro' : 'claro');
  });

  // ─── Busca e lista ──────────────────────────────────────────────────
  var lista = $('lista-unidades');
  var cartoes = Array.prototype.slice.call(lista.querySelectorAll('.unidade'));
  var unidades = cartoes.map(function (el) {
    return {
      el: el,
      id: el.dataset.id,
      busca: el.dataset.busca,
      cat: el.dataset.cat,
      regiao: el.dataset.regiao,
      lat: parseFloat(el.dataset.lat),
      lon: parseFloat(el.dataset.lon),
      nome: el.querySelector('h3').textContent,
      distancia: null,
      marcador: null
    };
  });
  var origem = null;
  var limiteVisivel = POR_PAGINA;

  function distanciaKm(lat1, lon1, lat2, lon2) {
    var rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad;
    var dLon = (lon2 - lon1) * rad;
    var a = Math.pow(Math.sin(dLat / 2), 2) +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.pow(Math.sin(dLon / 2), 2);
    return 6371 * 2 * Math.asin(Math.sqrt(a));
  }

  function formatarDistancia(km) {
    if (km < 1) return Math.round(km * 1000) + ' m';
    return km.toFixed(1).replace('.', ',') + ' km';
  }

  function filtradas() {
    var termos = normalizar($('busca').value).split(/\s+/).filter(Boolean);
    var cat = $('filtro-cat').value;
    var regiao = $('filtro-regiao').value;
    return unidades.filter(function (u) {
      if (cat && u.cat !== cat) return false;
      if (regiao && u.regiao !== regiao) return false;
      return termos.every(function (t) { return u.busca.indexOf(t) !== -1; });
    });
  }

  function atualizar() {
    var resultado = filtradas();
    if (origem) {
      unidades.forEach(function (u) {
        u.distancia = distanciaKm(origem.lat, origem.lon, u.lat, u.lon);
        var campo = u.el.querySelector('.distancia');
        campo.hidden = false;
        campo.textContent = formatarDistancia(u.distancia);
      });
      resultado.sort(function (a, b) { return a.distancia - b.distancia; });
    }
    var visiveis = {}, encontradas = {};
    resultado.forEach(function (u, i) {
      encontradas[u.id] = true;
      if (i < limiteVisivel) visiveis[u.id] = true;
      // Sem ponto de origem a ordem é a do HTML, e nenhum cartão precisa mudar de lugar.
      if (origem) lista.appendChild(u.el);
    });
    unidades.forEach(function (u) {
      if (u.el.hidden === !!visiveis[u.id]) {
        u.el.hidden = !visiveis[u.id];
        u.el.style.display = visiveis[u.id] ? '' : 'none';
      }
      if (u.marcador && mapa) {
        var naLista = !!encontradas[u.id];
        if (naLista && !mapa.hasLayer(u.marcador)) u.marcador.addTo(mapa);
        if (!naLista && mapa.hasLayer(u.marcador)) mapa.removeLayer(u.marcador);
      }
    });

    var mais = $('mostrar-mais');
    var restantes = resultado.length - limiteVisivel;
    mais.hidden = restantes <= 0;
    if (restantes > 0) mais.textContent = 'Mostrar mais ' + Math.min(restantes, POR_PAGINA) + ' de ' + restantes + ' restantes';

    var mensagem;
    if (!resultado.length) {
      mensagem = 'Nenhuma unidade encontrada. Tente outro nome, ou limpe os filtros.';
    } else {
      mensagem = resultado.length + (resultado.length === 1 ? ' unidade encontrada' : ' unidades encontradas');
      if (origem) mensagem += ', da mais perto para a mais longe. A mais perto: ' + resultado[0].nome + ' (' + formatarDistancia(resultado[0].distancia) + ').';
      else mensagem += '.';
    }
    $('status-busca').textContent = mensagem;
  }

  function aoFiltrar() {
    limiteVisivel = POR_PAGINA;
    atualizar();
  }
  $('busca').addEventListener('input', aoFiltrar);
  $('filtro-cat').addEventListener('change', aoFiltrar);
  $('filtro-regiao').addEventListener('change', function () {
    aoFiltrar();
    destacarZona();
  });
  $('mostrar-mais').addEventListener('click', function () {
    limiteVisivel += POR_PAGINA;
    atualizar();
  });

  // ─── Mapa ───────────────────────────────────────────────────────────
  var mapa = null;
  var marcadorOrigem = null;
  var zonas = null;
  var limiteCidade = null;

  function nomeDistrito(regiao) {
    return regiao.charAt(0) + regiao.slice(1).toLowerCase();
  }

  // Sem filtro, todas as zonas têm o mesmo peso. Com filtro, a escolhida se destaca.
  function estiloZona(regiao, escolhida) {
    var destacada = regiao === escolhida;
    return {
      className: 'zona',
      color: dados.coresDistrito[regiao],
      fillColor: dados.coresDistrito[regiao],
      weight: destacada ? 3 : 1.5,
      opacity: escolhida && !destacada ? 0.45 : 0.95,
      fillOpacity: !escolhida ? 0.24 : (destacada ? 0.4 : 0.07)
    };
  }

  function destacarZona() {
    if (!mapa || !zonas) return;
    var escolhida = $('filtro-regiao').value;
    var alvo = limiteCidade;
    zonas.eachLayer(function (camada) {
      var regiao = camada.feature.properties.regiao;
      camada.setStyle(estiloZona(regiao, escolhida));
      if (regiao === escolhida) alvo = camada.getBounds();
    });
    mapa.fitBounds(alvo);
  }

  function definirOrigem(lat, lon, descricao) {
    origem = { lat: lat, lon: lon };
    if (mapa) {
      if (marcadorOrigem) mapa.removeLayer(marcadorOrigem);
      marcadorOrigem = window.L.circleMarker([lat, lon], {
        radius: 8, color: '#0A6E6A', weight: 4, fillColor: '#FFFFFF', fillOpacity: 1
      }).addTo(mapa).bindTooltip(descricao);
      mapa.setView([lat, lon], Math.max(mapa.getZoom(), 13));
    }
    aoFiltrar();
  }

  function destacar(unidade) {
    unidades.forEach(function (u) { u.el.classList.remove('ativa'); });
    unidade.el.classList.add('ativa');
  }

  function popup(unidade) {
    var caixa = document.createElement('div');
    var nome = document.createElement('b');
    nome.textContent = unidade.nome;
    var info = document.createElement('span');
    info.textContent = dados.rotulos[unidade.cat] + ', Distrito ' + nomeDistrito(unidade.regiao);
    caixa.appendChild(nome);
    caixa.appendChild(info);
    return caixa;
  }

  function iniciarMapa() {
    var L = window.L;
    mapa = L.map('mapa', { scrollWheelZoom: false, maxZoom: 18 });
    var contorno = L.geoJSON(dados.limite, {
      interactive: false,
      style: { color: '#0A6E6A', weight: 2, fill: false }
    }).addTo(mapa);
    limiteCidade = contorno.getBounds();
    mapa.fitBounds(limiteCidade);

    // Ordem de cima para baixo: unidades, nomes dos distritos, zonas. Um nome nunca cobre uma unidade.
    mapa.createPane('zonas').style.zIndex = 300;
    mapa.createPane('nomes-zonas').style.zIndex = 350;
    zonas = L.geoJSON(dados.zonas, {
      interactive: false,
      pane: 'zonas',
      style: function (zona) { return estiloZona(zona.properties.regiao, ''); }
    }).addTo(mapa);
    dados.zonas.features.forEach(function (zona) {
      L.marker(zona.properties.rotulo, {
        interactive: false, keyboard: false, pane: 'nomes-zonas',
        icon: L.divIcon({
          className: 'rotulo-zona', iconSize: null,
          html: '<span>' + nomeDistrito(zona.properties.regiao) + '</span>'
        })
      }).addTo(mapa);
    });
    mapa.on('zoomend', function () {
      $('mapa').classList.toggle('perto', mapa.getZoom() >= 14);
    });

    var erros = 0, carregados = 0, avisado = false;
    // O OpenStreetMap exige o cabeçalho Referer, que não existe ao abrir o painel como arquivo,
    // e responde com uma imagem de bloqueio e status 200. O Esri não depende disso.
    // Cidade inteira: base cinza, limpa. A partir do zoom 14: mapa com os nomes das ruas,
    // que a base cinza não traz em Campinas.
    var servidor = 'https://server.arcgisonline.com/ArcGIS/rest/services/';
    var camadas = [
      L.tileLayer(servidor + 'Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        maxZoom: 13, attribution: 'Mapa &copy; <a href="https://www.esri.com/">Esri</a> e colaboradores'
      }),
      L.tileLayer(servidor + 'Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 13, zIndex: 2 }),
      L.tileLayer(servidor + 'World_Street_Map/MapServer/tile/{z}/{y}/{x}', { minZoom: 14, maxZoom: 18 })
    ];
    camadas.forEach(function (camada) {
      camada.on('tileload', function () { carregados += 1; });
      camada.on('tileerror', function () {
        erros += 1;
        if (!avisado && erros >= 4 && carregados === 0) {
          avisado = true;
          $('aviso-mapa').textContent = 'Sem conexão com o mapa de ruas. As unidades e o limite da cidade continuam visíveis.';
        }
      });
      camada.addTo(mapa);
    });

    unidades.forEach(function (u) {
      // Em tela estreita os pontos ficam menores, para não esconderem as zonas e seus nomes.
      var escala = window.innerWidth < 600 ? 0.62 : 1;
      var raio = (u.cat === 'Hospital' ? 9 : (u.cat === 'UPA' ? 8 : 6)) * escala;
      u.marcador = L.circleMarker([u.lat, u.lon], {
        radius: raio, fillColor: dados.cores[u.cat], color: '#FFFFFF', weight: 1.5, fillOpacity: 0.95
      }).addTo(mapa).bindPopup(popup(u));
      u.marcador.on('click', function () { destacar(u); });
      var botao = u.el.querySelector('.ver-no-mapa');
      botao.hidden = false;
      botao.addEventListener('click', function () {
        destacar(u);
        mapa.setView([u.lat, u.lon], 15);
        u.marcador.openPopup();
        $('mapa').scrollIntoView({ block: 'center' });
      });
    });

    mapa.on('click', function (ev) {
      definirOrigem(ev.latlng.lat, ev.latlng.lng, 'Ponto marcado');
    });
  }

  var botaoLocal = $('usar-local');
  botaoLocal.addEventListener('click', function () {
    var status = $('status-busca');
    if (!navigator.geolocation) {
      status.textContent = 'Este navegador não informa a localização. Busque pelo nome do bairro ou clique no mapa.';
      return;
    }
    status.textContent = 'Buscando sua localização...';
    navigator.geolocation.getCurrentPosition(function (pos) {
      definirOrigem(pos.coords.latitude, pos.coords.longitude, 'Você está aqui');
    }, function () {
      status.textContent = 'Não foi possível obter sua localização. Busque pelo nome do bairro ou clique no mapa.';
    }, { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 });
  });

  // ─── Início ─────────────────────────────────────────────────────────
  // A lista funciona mesmo se o mapa ou os gráficos falharem neste navegador.
  // Ela vem primeiro: o mapa mede a página, e sem isso mediria os 84 cartões abertos.
  atualizar();
  lista.classList.add('pronta');
  try {
    iniciarMapa();
  } catch (erro) {
    mapa = null;
    $('mapa').hidden = true;
    $('aviso-mapa').textContent = 'O mapa não pôde ser exibido neste navegador. Use a lista de unidades.';
  }
  iniciarGraficos();

  window.__painelPronto = true;
})();
