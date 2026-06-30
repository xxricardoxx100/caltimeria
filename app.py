from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import asyncio
from concurrent.futures import ThreadPoolExecutor

from satlima import consultar

app = FastAPI(title="Consulta SAT Lima")
executor = ThreadPoolExecutor(max_workers=2)

HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Consulta SAT Lima</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f0f2f5; display: flex; justify-content: center; padding: 40px 20px; min-height: 100vh; }
  .card { background: white; border-radius: 12px; padding: 32px; width: 100%; max-width: 720px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); align-self: flex-start; }
  h1 { color: #1a73e8; margin-bottom: 6px; font-size: 26px; }
  .subtitle { color: #666; margin-bottom: 28px; font-size: 14px; }
  .input-row { display: flex; gap: 10px; margin-bottom: 18px; }
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
  .status { padding: 14px 16px; border-radius: 8px; margin-bottom: 18px; font-size: 14px; display: none; }
  .loading { background: #fff3cd; border: 1px solid #ffc107; color: #856404; display: block; }
  .error   { background: #f8d7da; border: 1px solid #dc3545; color: #721c24; display: block; }
  .ok      { background: #d4edda; border: 1px solid #28a745; color: #155724; display: block; }
  #results { display: none; margin-top: 8px; }
  .section { margin-bottom: 28px; }
  .section h2 { font-size: 17px; color: #333; padding-bottom: 8px; border-bottom: 2px solid #eee; margin-bottom: 14px; }
  .total-badge { display: inline-block; background: #e8f0fe; color: #1a73e8; padding: 6px 18px; border-radius: 20px; font-weight: bold; font-size: 20px; }
  .sin-deuda { color: #28a745; font-style: italic; padding: 6px 0; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th { background: #f8f9fa; padding: 10px 12px; text-align: left; color: #555; border-bottom: 2px solid #dee2e6; }
  td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; }
  tr:last-child td { border-bottom: none; }
  .total-row { text-align: right; margin-top: 14px; }
  .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #856404; border-top-color: transparent; border-radius: 50%; animation: spin .7s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<div class="card">
  <h1>Consulta SAT Lima</h1>
  <p class="subtitle">Impuestos vehiculares y papeletas por placa</p>

  <div class="input-row">
    <input type="text" id="placa" placeholder="Ej: ABC123" maxlength="10" />
    <button id="btn" onclick="consultar()">Consultar</button>
  </div>

  <div class="status" id="status"></div>

  <div id="results">
    <div class="section">
      <h2>Impuesto Vehicular</h2>
      <div id="impuesto-content"></div>
    </div>
    <div class="section">
      <h2>Papeletas</h2>
      <div id="papeletas-content"></div>
    </div>
  </div>
</div>

<script>
async function consultar() {
  const placa = document.getElementById('placa').value.trim().toUpperCase();
  if (!placa) { alert('Ingresa una placa'); return; }

  const btn    = document.getElementById('btn');
  const status = document.getElementById('status');
  const res    = document.getElementById('results');

  btn.disabled = true;
  res.style.display = 'none';
  status.className = 'status loading';
  status.innerHTML = '<span class="spinner"></span>Abriendo Chrome para consultar la placa <strong>' + placa + '</strong>... Si aparece el CAPTCHA, resuélvelo en esa ventana. Puede tardar hasta 90 segundos.';

  try {
    const resp = await fetch('/consultar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({placa})
    });

    const data = await resp.json();

    if (!resp.ok) {
      status.className = 'status error';
      status.textContent = 'Error: ' + (data.detail || 'No se pudo consultar');
      return;
    }

    mostrarResultados(data);
    status.className = 'status ok';
    status.textContent = 'Consulta completada para la placa ' + placa;
    res.style.display = 'block';

  } catch(e) {
    status.className = 'status error';
    status.textContent = 'Error de conexion: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

function mostrarResultados(data) {
  // Impuesto vehicular
  const impDiv   = document.getElementById('impuesto-content');
  const totalImp = data.impuesto_vehicular.total_web;
  if (totalImp === '0.00') {
    impDiv.innerHTML = '<p class="sin-deuda">Sin deuda de impuesto vehicular</p>';
  } else {
    impDiv.innerHTML = '<span class="total-badge">S/ ' + totalImp + '</span>';
  }

  // Papeletas
  const papDiv   = document.getElementById('papeletas-content');
  const items    = data.papeletas.items;
  const totalPap = data.papeletas.total_web;

  if (totalPap === '0.00' || items.length === 0) {
    papDiv.innerHTML = '<p class="sin-deuda">Sin papeletas pendientes</p>';
  } else {
    let html = '<table><thead><tr><th>Falta</th><th>Fecha</th><th>Monto</th></tr></thead><tbody>';
    for (const it of items) {
      html += '<tr><td>' + esc(it.Falta) + '</td><td>' + esc(it.Fecha) + '</td><td>S/ ' + esc(it.Monto) + '</td></tr>';
    }
    html += '</tbody></table>';
    html += '<p class="total-row">Total oficial: <span class="total-badge">S/ ' + esc(totalPap) + '</span></p>';
    papDiv.innerHTML = html;
  }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('placa').addEventListener('keydown', e => {
  if (e.key === 'Enter') consultar();
});
</script>
</body>
</html>"""


class PlacaRequest(BaseModel):
    placa: str


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


@app.post("/consultar")
async def consultar_placa(req: PlacaRequest):
    try:
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(
            executor,
            lambda: consultar(req.placa, headless=False, manual_captcha=True)
        )
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al consultar: {e}")
