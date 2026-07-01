#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de Certificados de Inspeccion Tecnica Vehicular (CITV) por PLACA en el MTC.
Tiene captcha de 6 digitos, resuelto con pytesseract. Usa Chrome para bypassear Cloudflare.
"""

import argparse
import base64
import json
import platform
import re
import sys
import os
import time
import urllib.parse

import cv2
import numpy as np
import pytesseract
import undetected_chromedriver as uc

from navegador import LOCK_CHROMEDRIVER, CHROME_VERSION_MAIN, ruta_chromedriver, SEMAFORO_CHROME, aplicar_flags_memoria

URL_PAGINA = "https://rec.mtc.gob.pe/Citv/ArConsultaCitv"

if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_driver():
    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    aplicar_flags_memoria(options)
    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, driver_executable_path=ruta_chromedriver(), version_main=CHROME_VERSION_MAIN)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(20)
    return driver


def _fetch_captcha_raw(driver):
    """Ejecuta el fetch del captcha desde Chrome y devuelve {status, body}."""
    return driver.execute_async_script("""
        var cb = arguments[arguments.length-1];
        fetch('/CITV/refrescarCaptcha')
            .then(function(r){ return r.text().then(function(t){ return {status: r.status, body: t}; }); })
            .then(function(d){ cb(d); })
            .catch(function(e){ cb({status: -1, body: String(e)}); });
    """)


def resolver_captcha(driver, diagnostico=False):
    res = _fetch_captcha_raw(driver)
    status = res.get("status") if isinstance(res, dict) else None
    body = (res.get("body") if isinstance(res, dict) else "") or ""

    if status != 200:
        if diagnostico:
            print(f"  [RT] captcha status={status} body[:150]={body[:150]!r}", flush=True)
        return ""

    try:
        b64 = (json.loads(body) or {}).get("orResult")
    except Exception:
        if diagnostico:
            print(f"  [RT] captcha respuesta no-JSON body[:150]={body[:150]!r}", flush=True)
        return ""

    if not b64:
        if diagnostico:
            print(f"  [RT] captcha orResult vacio", flush=True)
        return ""

    raw = base64.b64decode(b64)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return ""
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    config = "--psm 8 -c tessedit_char_whitelist=0123456789"
    texto = pytesseract.image_to_string(binary, config=config).strip().replace(" ", "").replace("\n", "")
    return texto


def buscar(driver, placa, captcha):
    params = urllib.parse.urlencode({"pArrParametros": f"1|{placa}||{captcha}"})
    result = driver.execute_async_script(f"""
        var cb = arguments[arguments.length-1];
        fetch('/CITV/JrCITVConsultarFiltro?{params}')
            .then(function(r){{ return r.ok ? r.json() : Promise.reject(r.status); }})
            .then(function(d){{ cb(d); }})
            .catch(function(){{ cb(null); }});
    """)
    return result


def consultar(placa: str, max_intentos: int = 15):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    SEMAFORO_CHROME.acquire()
    driver = None
    try:
        driver = crear_driver()
        driver.get(URL_PAGINA)
        time.sleep(3)  # esperar que Cloudflare pase el challenge

        for intento in range(max_intentos):
            # Diagnostico solo en los primeros intentos para no llenar el log.
            texto = resolver_captcha(driver, diagnostico=(intento < 3))
            if len(texto) != 6:
                # El captcha aun no carga (Cloudflare no ha pasado su challenge
                # o el OCR fallo). Pausar para dar tiempo a que el challenge se
                # resuelva en vez de quemar las 15 iteraciones en menos de 1s.
                time.sleep(1)
                continue

            data = buscar(driver, placa, texto)
            if intento < 3:
                print(f"  [RT] intento {intento} captcha='{texto}' -> "
                      f"data={'None' if data is None else str(data)[:150]!r}", flush=True)

            if data is None or data.get("orCodigo") == "-1":
                # Respuesta invalida (Cloudflare) o captcha incorrecto: reintentar.
                time.sleep(1)
                continue

            if not data.get("orStatus"):
                raise RuntimeError("Ocurrio un error al consultar el servicio del MTC.")

            # Aqui ya tenemos una respuesta valida del servidor: recien ahora
            # un orResult vacio significa realmente "no hay datos".
            resultado = data.get("orResult") or []
            if not resultado:
                return {"sin_resultados": True}

            parsed = json.loads(resultado[0])
            if not parsed:
                return {"sin_resultados": True}
            return parsed

        # Se agotaron los intentos sin una sola respuesta valida del servidor:
        # fue un problema de captcha/Cloudflare, NO ausencia de datos. Lanzamos
        # error para que la UI muestre "reintentar" en vez de "sin informacion".
        raise RuntimeError("No se pudo resolver el captcha del MTC tras varios intentos.")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        SEMAFORO_CHROME.release()


def main():
    parser = argparse.ArgumentParser(description="Consulta de CITV (revision tecnica) por placa - MTC")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    args = parser.parse_args()

    try:
        resultado = consultar(args.placa)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    if isinstance(resultado, dict) and resultado.get("sin_resultados"):
        if args.json:
            print(json.dumps({"sin_resultados": True}, ensure_ascii=False))
        else:
            placa_norm = normalizar_placa(args.placa)
            print(f"\n===== REVISION TECNICA (CITV) PARA LA PLACA {placa_norm} =====")
            print("  No se encontro informacion de revision tecnica para esta placa.")
            print("===================================================\n")
        sys.stdout.flush()
        os._exit(0)

    registros = resultado if isinstance(resultado, list) else [resultado]
    ultimo = registros[0] if registros else {}

    if args.json:
        print(json.dumps(ultimo, ensure_ascii=False, indent=2))
        sys.stdout.flush()
        os._exit(0)

    placa_norm = normalizar_placa(args.placa)
    print(f"\n===== REVISION TECNICA (CITV) PARA LA PLACA {placa_norm} =====")
    if not ultimo:
        print("  No se encontro informacion de revision tecnica para esta placa.")
    else:
        print(f"  Certificado : {ultimo.get('NRO_CERTI', '')}")
        print(f"  Inicio      : {ultimo.get('REVISIONVIGENCIAINICIO', '')}")
        print(f"  Fin         : {ultimo.get('REVISIONVIGENCIAFINAL', '')}")
        print(f"  Resultado   : {ultimo.get('RESULTADO', '')}")
        estado = ultimo.get("ESTADO", "")
        if estado:
            print(f"  Estado      : {estado}")
        obs = ultimo.get("OBSERVACION", "")
        if obs:
            print(f"  Observacion : {obs}")
    print("===================================================\n")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
