from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncio
from concurrent.futures import ThreadPoolExecutor

from satlima import consultar as consultar_satlima
from callao import consultar as consultar_callao
from sutran import consultar as consultar_sutran
from atu import consultar as consultar_atu
from soat import consultar as consultar_soat
from revisiontecnica import consultar as consultar_revisiontecnica
from consultaveh import consultar as consultar_sunarp

app = FastAPI(title="Consulta Vehicular")
executor = ThreadPoolExecutor(max_workers=7)


async def ejecutar(func, placa, **kwargs):
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(executor, lambda: func(placa, **kwargs))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar: {e}")


HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Consulta Vehicular</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f0f2f5; padding: 40px 20px; min-height: 100vh; }
  .top { max-width: 960px; margin: 0 auto 24px; background: white; border-radius: 12px; padding: 32px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
  h1 { color: #1a73e8; margin-bottom: 6px; font-size: 26px; }
  .subtitle { color: #666; margin-bottom: 28px; font-size: 14px; }
  .input-row { display: flex; gap: 10px; }
  input[type=text] {
    flex: 1; padding: 12px 16px; border: 2px solid #ddd; border-radius: 8px;
    font-size: 20px; text-transform: uppercase; letter-spacing: 3px; font-weight: bold;
  }
  input[type=text]:focus { outline: none; border-color: #1a73e8; }
  button {
    padding: 12px 28px; background: #1a73e8; color: white;
    border: none; border-radius: 8px; font-size: 16px; cursor: pointer; white-space: nowrap;
  }
  button:hover { background: #1557b0; }
  button:disabled { background: #aaa; cursor: not-allowed; }

  .grid { max-width: 960px; margin: 0 auto; display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }

  .card { background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); }
  .card h2 { font-size: 17px; color: #333; padding-bottom: 8px; border-bottom: 2px solid #eee; margin-bottom: 14px; }

  .status { padding: 10px 14px; border-radius: 8px; margin-bottom: 12px; font-size: 13px; }
  .status.idle { background: #f0f2f5; color: #888; }
  .status.loading { background: #fff3cd; border: 1px solid #ffc107; color: #856404; }
  .status.error   { background: #f8d7da; border: 1px solid #dc3545; color: #721c24; }
  .status.ok      { background: #d4edda; border: 1px solid #28a745; color: #155724; }

  .total-badge { display: inline-block; background: #e8f0fe; color: #1a73e8; padding: 6px 18px; border-radius: 20px; font-weight: bold; font-size: 18px; }
  .sin-deuda { color: #28a745; font-style: italic; padding: 6px 0; font-size: 14px; }
  .vigente { color: #28a745; font-weight: bold; }
  .no-vigente { color: #dc3545; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { background: #f8f9fa; padding: 8px 10px; text-align: left; color: #555; border-bottom: 2px solid #dee2e6; }
  td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; }
  tr:last-child td { border-bottom: none; }
  .total-row { text-align: right; margin-top: 12px; }
  .ficha { font-size: 14px; }
  .ficha div { padding: 4px 0; }
  .ficha b { color: #555; }
  .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid #856404; border-top-color: transparent; border-radius: 50%; animation: spin .7s linear infinite; margin-right: 6px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div class="top">
  <h1>Consulta Vehicular</h1>
  <p class="subtitle">SAT Lima, Callao, SUTRAN, ATU, SOAT y Revision Tecnica (CITV) por placa</p>
  <div class="input-row">
    <input type="text" id="placa" placeholder="Ej: ABC123" maxlength="10" />
    <button id="btn" onclick="consultarTodo()">Consultar Todo</button>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>SAT Lima (Impuesto y Papeletas)</h2>
    <div class="status idle" id="status-satlima">Esperando consulta.</div>
    <div id="content-satlima"></div>
  </div>

  <div class="card">
    <h2>Callao (Papeletas)</h2>
    <div class="status idle" id="status-callao">Esperando consulta.</div>
    <div id="content-callao"></div>
  </div>

  <div class="card">
    <h2>SUTRAN (Infracciones)</h2>
    <div class="status idle" id="status-sutran">Esperando consulta.</div>
    <div id="content-sutran"></div>
  </div>

  <div class="card">
    <h2>ATU (Infracciones)</h2>
    <div class="status idle" id="status-atu">Esperando consulta.</div>
    <div id="content-atu"></div>
  </div>

  <div class="card">
    <h2>SOAT (Vigencia)</h2>
    <div class="status idle" id="status-soat">Esperando consulta.</div>
    <div id="content-soat"></div>
  </div>

  <div class="card">
    <h2>Revision Tecnica (CITV)</h2>
    <div class="status idle" id="status-revisiontecnica">Esperando consulta.</div>
    <div id="content-revisiontecnica"></div>
  </div>

  <div class="card" style="grid-column: 1 / -1;">
    <h2>Consulta Vehicular (SUNARP)</h2>
    <div class="status idle" id="status-sunarp">Esperando consulta.</div>
    <div id="content-sunarp"></div>
  </div>
</div>

<script>
function esc(s) {
  return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function setEstado(fuente, clase, texto) {
  const el = document.getElementById('status-' + fuente);
  el.className = 'status ' + clase;
  el.innerHTML = clase === 'loading' ? '<span class="spinner"></span>' + texto : texto;
}

function tablaDeuda(items, campos, totalLabel, total) {
  if (!items.length) return '<p class="sin-deuda">Sin registros pendientes</p>';
  let html = '<table><thead><tr>';
  for (const c of campos) html += '<th>' + esc(c) + '</th>';
  html += '</tr></thead><tbody>';
  for (const it of items) {
    html += '<tr>';
    for (const c of campos) html += '<td>' + esc(it[c]) + '</td>';
    html += '</tr>';
  }
  html += '</tbody></table>';
  if (total !== undefined) {
    html += '<p class="total-row">' + esc(totalLabel) + ': <span class="total-badge">S/ ' + esc(total) + '</span></p>';
  }
  return html;
}

const renderizar = {
  satlima(data) {
    const div = document.getElementById('content-satlima');
    const totalImp = data.impuesto_vehicular.total_web;
    const impHtml = (totalImp === '0.00')
      ? '<p class="sin-deuda">Sin deuda de impuesto vehicular</p>'
      : '<span class="total-badge">S/ ' + esc(totalImp) + '</span>';

    const totalMultas = data.multas_tributarias ? data.multas_tributarias.total_web : '0.00';
    const multasHtml = (totalMultas === '0.00')
      ? ''
      : '<p style="margin-top:14px"><b>Multas Tributarias:</b></p>' +
        '<span class="total-badge">S/ ' + esc(totalMultas) + '</span>';

    const pap = data.papeletas;
    const papHtml = tablaDeuda(pap.items, ['Falta', 'Fecha', 'Monto'], 'Total oficial', pap.total_web);
    div.innerHTML = '<p><b>Impuesto Vehicular:</b></p>' + impHtml +
                    multasHtml +
                    '<p style="margin-top:14px"><b>Papeletas:</b></p>' + papHtml;
  },

  callao(data) {
    const div = document.getElementById('content-callao');
    if (data.sin_resultados) {
      div.innerHTML = '<p class="sin-deuda">Sin papeletas pendientes</p>';
      return;
    }
    div.innerHTML = tablaDeuda(data.items, ['Codigo', 'Fecha', 'Total'], 'Total oficial', data.suma_calculada);
  },

  sutran(data) {
    const div = document.getElementById('content-sutran');
    if (data.sin_resultados) {
      div.innerHTML = '<p class="sin-deuda">No se encontraron infracciones</p>';
      return;
    }
    div.innerHTML = tablaDeuda(data.items, ['Numero de documento', 'Fecha', 'Clasificacion']);
  },

  atu(data) {
    const div = document.getElementById('content-atu');
    if (data.sin_resultados) {
      div.innerHTML = '<p class="sin-deuda">Sin infracciones registradas</p>';
      return;
    }
    div.innerHTML = tablaDeuda(data.items, ['Codigo', 'Fecha', 'Total'], 'Total oficial', data.suma_calculada);
  },

  soat(data) {
    const div = document.getElementById('content-soat');
    if (data.sin_resultados) {
      div.innerHTML = '<p class="sin-deuda">Sin informacion de SOAT para esta placa</p>';
      return;
    }
    const clase = data.vigente ? 'vigente' : 'no-vigente';
    const etiqueta = data.vigente ? 'VIGENTE' : 'NO VIGENTE';
    div.innerHTML = '<div class="ficha">' +
      '<div><b>Estado:</b> ' + esc(data.estado) + ' (<span class="' + clase + '">' + etiqueta + '</span>)</div>' +
      '<div><b>Inicio:</b> ' + esc(data.inicio) + '</div>' +
      '<div><b>Fin:</b> ' + esc(data.fin) + '</div>' +
      '</div>';
  },

  sunarp(data) {
    const div = document.getElementById('content-sunarp');
    if (data.sin_resultados || !data.imagen_b64) {
      div.innerHTML = '<p class="sin-deuda">Sin informacion de consulta vehicular para esta placa</p>';
      return;
    }
    div.innerHTML = '<img src="data:image/png;base64,' + data.imagen_b64 + '" style="width:100%;border-radius:4px;margin-top:4px;" />';
  },

  revisiontecnica(data) {
    const div = document.getElementById('content-revisiontecnica');
    const u = data.ultimo;
    if (data.sin_resultados || !u) {
      div.innerHTML = '<p class="sin-deuda">Sin informacion de revision tecnica para esta placa</p>';
      return;
    }
    let html = '<div class="ficha">' +
      '<div><b>Certificado:</b> ' + esc(u.NRO_CERTI) + '</div>' +
      '<div><b>Inicio:</b> ' + esc(u.REVISIONVIGENCIAINICIO) + '</div>' +
      '<div><b>Fin:</b> ' + esc(u.REVISIONVIGENCIAFINAL) + '</div>' +
      '<div><b>Resultado:</b> ' + esc(u.RESULTADO) + '</div>';
    if (u.ESTADO) html += '<div><b>Estado:</b> ' + esc(u.ESTADO) + '</div>';
    if (u.OBSERVACION) html += '<div><b>Observacion:</b> ' + esc(u.OBSERVACION) + '</div>';
    html += '</div>';
    div.innerHTML = html;
  },
};

async function consultarFuente(fuente, placa) {
  setEstado(fuente, 'loading', 'Consultando...');
  document.getElementById('content-' + fuente).innerHTML = '';
  try {
    const resp = await fetch('/consultar/' + fuente, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({placa})
    });
    const data = await resp.json();
    if (!resp.ok) {
      setEstado(fuente, 'error', 'Error: ' + (data.detail || 'No se pudo consultar'));
      return;
    }
    renderizar[fuente](data);
    setEstado(fuente, 'ok', 'Consulta completada');
  } catch (e) {
    setEstado(fuente, 'error', 'Error de conexion: ' + e.message);
  }
}

async function consultarTodo() {
  const placa = document.getElementById('placa').value.trim().toUpperCase();
  if (!placa) { alert('Ingresa una placa'); return; }

  const btn = document.getElementById('btn');
  btn.disabled = true;

  try {
    const fuentes = ['satlima', 'callao', 'sutran', 'atu', 'soat', 'revisiontecnica', 'sunarp'];
    await Promise.allSettled(fuentes.map(f => consultarFuente(f, placa)));
  } finally {
    btn.disabled = false;
  }
}

document.getElementById('placa').addEventListener('keydown', e => {
  if (e.key === 'Enter') consultarTodo();
});
</script>
</body>
</html>"""


class PlacaRequest(BaseModel):
    placa: str


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.post("/consultar/satlima")
async def consultar_satlima_ep(req: PlacaRequest):
    return await ejecutar(consultar_satlima, req.placa, headless=True)


@app.post("/consultar/callao")
async def consultar_callao_ep(req: PlacaRequest):
    return await ejecutar(consultar_callao, req.placa)


@app.post("/consultar/sutran")
async def consultar_sutran_ep(req: PlacaRequest):
    return await ejecutar(consultar_sutran, req.placa)


@app.post("/consultar/atu")
async def consultar_atu_ep(req: PlacaRequest):
    return await ejecutar(consultar_atu, req.placa)


@app.post("/consultar/soat")
async def consultar_soat_ep(req: PlacaRequest):
    return await ejecutar(consultar_soat, req.placa)


@app.post("/consultar/sunarp")
async def consultar_sunarp_ep(req: PlacaRequest):
    return await ejecutar(consultar_sunarp, req.placa)


@app.post("/consultar/revisiontecnica")
async def consultar_revisiontecnica_ep(req: PlacaRequest):
    try:
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(executor, lambda: consultar_revisiontecnica(req.placa))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar: {e}")

    if isinstance(resultado, dict) and resultado.get("sin_resultados"):
        return {"ultimo": None, "sin_resultados": True}

    registros = resultado if isinstance(resultado, list) else [resultado]
    ultimo = registros[0] if registros else None
    return {"ultimo": ultimo, "sin_resultados": not registros}
