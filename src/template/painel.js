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
  var graficosProntos = false;

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

  function desenharGraficos() {
    Object.keys(dados.figuras).forEach(function (id) {
      var alvo = $(id);
      if (!alvo) return;
      var figura = dados.figuras[id];
      var promessa = window.Plotly.newPlot(alvo, figura.data, figura.layout, {
        displayModeBar: false, responsive: true, locale: 'pt-BR'
      });
      promessa.then(function () { window.Plotly.relayout(alvo, estiloTema()); });
    });
    graficosProntos = true;
  }

  function avisarFalhaGraficos() {
    document.querySelectorAll('.grafico').forEach(function (alvo) {
      var aviso = document.createElement('p');
      aviso.className = 'grafico-erro';
      aviso.textContent = 'Não foi possível desenhar este gráfico neste navegador. Os mesmos números estão no quadro por distrito.';
      alvo.appendChild(aviso);
    });
  }

  // ─── Tema ───────────────────────────────────────────────────────────
  function rotuloTema() {
    $('alternar-tema').textContent = temaAtual() === 'claro' ? 'Mudar para tema escuro' : 'Mudar para tema claro';
  }

  function aplicarTema(tema) {
    document.documentElement.setAttribute('data-tema', tema);
    try { localStorage.setItem('tema', tema); } catch (erro) { /* navegação privada */ }
    rotuloTema();
    if (graficosProntos) {
      Object.keys(dados.figuras).forEach(function (id) { window.Plotly.relayout($(id), estiloTema()); });
    }
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
    var visiveis = {};
    resultado.forEach(function (u, i) {
      if (i < limiteVisivel) visiveis[u.id] = true;
      lista.appendChild(u.el);
    });
    unidades.forEach(function (u) {
      u.el.hidden = !visiveis[u.id];
      u.el.style.display = visiveis[u.id] ? '' : 'none';
      if (u.marcador && mapa) {
        var naLista = resultado.indexOf(u) !== -1;
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
  $('filtro-regiao').addEventListener('change', aoFiltrar);
  $('mostrar-mais').addEventListener('click', function () {
    limiteVisivel += POR_PAGINA;
    atualizar();
  });

  // ─── Mapa ───────────────────────────────────────────────────────────
  var mapa = null;
  var marcadorOrigem = null;

  function definirOrigem(lat, lon, descricao) {
    origem = { lat: lat, lon: lon };
    if (mapa) {
      if (marcadorOrigem) mapa.removeLayer(marcadorOrigem);
      marcadorOrigem = window.L.circleMarker([lat, lon], {
        radius: 8, color: '#1D4FB8', weight: 4, fillColor: '#FFFFFF', fillOpacity: 1
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
    info.textContent = dados.rotulos[unidade.cat] + ' · Distrito ' + unidade.regiao.charAt(0) + unidade.regiao.slice(1).toLowerCase();
    caixa.appendChild(nome);
    caixa.appendChild(info);
    return caixa;
  }

  function iniciarMapa() {
    var L = window.L;
    mapa = L.map('mapa', { scrollWheelZoom: false });
    var contorno = L.geoJSON(dados.limite, {
      interactive: false,
      style: { color: '#4F86EA', weight: 2, fillColor: '#4F86EA', fillOpacity: 0.06 }
    }).addTo(mapa);
    mapa.fitBounds(contorno.getBounds());

    var erros = 0, carregados = 0, avisado = false;
    var ruas = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19, referrerPolicy: 'strict-origin-when-cross-origin'
    });
    ruas.on('tileload', function () { carregados += 1; });
    ruas.on('tileerror', function () {
      erros += 1;
      if (!avisado && erros >= 4 && carregados === 0) {
        avisado = true;
        $('aviso-mapa').textContent = 'Sem conexão com o mapa de ruas. As unidades e o limite da cidade continuam visíveis.';
      }
    });
    ruas.addTo(mapa);

    unidades.forEach(function (u) {
      var raio = u.cat === 'Hospital' ? 9 : (u.cat === 'UPA' ? 8 : 6);
      u.marcador = L.circleMarker([u.lat, u.lon], {
        radius: raio, fillColor: dados.cores[u.cat], color: '#0A0E1A', weight: 1.5, fillOpacity: 0.95
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
  try {
    iniciarMapa();
  } catch (erro) {
    mapa = null;
    $('mapa').hidden = true;
    $('aviso-mapa').textContent = 'O mapa não pôde ser exibido neste navegador. Use a lista de unidades.';
  }
  atualizar();
  try {
    desenharGraficos();
  } catch (erro) {
    avisarFalhaGraficos();
  }

  window.__painelPronto = true;
})();
