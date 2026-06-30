#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de record de infracciones por PLACA en SUTRAN.

El captcha de esta web (4 letras) se genera a partir del parametro
"numAleatorio" en la URL de la imagen (iframe#iimage) y ese mismo valor
es la respuesta correcta (se ve reflejado tambien en la validacion JS
del formulario: codigoGenrado). No requiere OCR.
"""

import argparse
import json
import re
import sys
import time
import os

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from navegador import LOCK_CHROMEDRIVER, CHROME_VERSION_MAIN, ruta_chromedriver

URL = "https://webexterno.sutran.gob.pe/WebExterno/Pages/frmRecordInfracciones.aspx"

INPUT_PLACA_ID = "txtPlaca"
INPUT_CAPTCHA_ID = "TxtCodImagen"
BOTON_BUSCAR_ID = "BtnBuscar"
CAPTCHA_IFRAME_ID = "iimage"

MAX_INTENTOS = 4


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_driver(headless: bool = True):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=es-PE")

    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, driver_executable_path=ruta_chromedriver(), version_main=CHROME_VERSION_MAIN)
    driver.set_page_load_timeout(30)
    return driver


def obtener_codigo_captcha(wait) -> str:
    iframe = wait.until(EC.presence_of_element_located((By.ID, CAPTCHA_IFRAME_ID)))
    src = iframe.get_attribute("src")
    match = re.search(r"numAleatorio=([A-Za-z0-9]+)", src or "")
    return match.group(1).upper() if match else None


def extraer_resultados(driver):
    resultados = {"items": [], "sin_resultados": False}

    try:
        mensaje = driver.find_element(By.ID, "LblMensaje").text.strip()
        if "no se encontraron" in mensaje.lower():
            resultados["sin_resultados"] = True
            return resultados
    except NoSuchElementException:
        pass

    try:
        tabla = driver.find_element(By.ID, "gvDeudas")
        headers = [th.text.strip().lower() for th in tabla.find_elements(By.CSS_SELECTOR, "th")]

        idx_numero = next((i for i, h in enumerate(headers) if "mero" in h), None)
        idx_fecha = next((i for i, h in enumerate(headers) if "fecha" in h), None)
        idx_clasif = next((i for i, h in enumerate(headers) if "clasifica" in h), None)

        for fila in tabla.find_elements(By.CSS_SELECTOR, "tr"):
            celdas = [td.text.strip() for td in fila.find_elements(By.TAG_NAME, "td")]
            if not celdas or not any(celdas):
                continue

            numero = celdas[idx_numero] if idx_numero is not None and idx_numero < len(celdas) else ""
            fecha = celdas[idx_fecha] if idx_fecha is not None and idx_fecha < len(celdas) else ""
            clasificacion = celdas[idx_clasif] if idx_clasif is not None and idx_clasif < len(celdas) else ""

            if not numero and not fecha and not clasificacion:
                continue

            resultados["items"].append({
                "Numero de documento": numero,
                "Fecha": fecha,
                "Clasificacion": clasificacion,
            })
    except NoSuchElementException:
        pass

    if not resultados["items"]:
        resultados["sin_resultados"] = True

    return resultados


def consultar(placa: str, headless: bool = True, max_intentos: int = MAX_INTENTOS):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    driver = crear_driver(headless=headless)
    wait = WebDriverWait(driver, 15)
    try:
        for intento in range(1, max_intentos + 1):
            driver.get(URL)
            time.sleep(2)

            codigo = obtener_codigo_captcha(wait)
            if not codigo:
                print(f"  -> [Intento {intento}] No se pudo leer el captcha, reintentando...")
                continue

            campo_placa = wait.until(EC.presence_of_element_located((By.ID, INPUT_PLACA_ID)))
            campo_placa.clear()
            campo_placa.send_keys(placa)

            driver.find_element(By.ID, INPUT_CAPTCHA_ID).clear()
            driver.find_element(By.ID, INPUT_CAPTCHA_ID).send_keys(codigo)
            driver.find_element(By.ID, BOTON_BUSCAR_ID).click()

            try:
                wait.until(EC.staleness_of(campo_placa))
            except TimeoutException:
                pass
            time.sleep(2)

            try:
                mensaje_error = driver.find_element(By.ID, "LblMensaje").text.strip()
            except NoSuchElementException:
                mensaje_error = ""

            if "incorrecto" in mensaje_error.lower() or "código de la imagen" in mensaje_error.lower():
                print(f"  -> [Intento {intento}] Captcha rechazado, reintentando...")
                continue

            print(f"  -> Busqueda realizada (captcha '{codigo}').")
            return extraer_resultados(driver)

        raise RuntimeError(f"No se pudo completar la busqueda tras {max_intentos} intentos.")
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Record de infracciones por placa - SUTRAN")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--ver-navegador", action="store_true", help="Mostrar la ventana de Chrome")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    args = parser.parse_args()

    headless = not args.ver_navegador

    try:
        resultados = consultar(args.placa, headless=headless)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
        sys.stdout.flush()
        os._exit(0)

    print(f"\n===== RECORD DE INFRACCIONES - PLACA {normalizar_placa(args.placa)} =====")
    if resultados["sin_resultados"] or not resultados["items"]:
        print("  No se encontraron infracciones pendientes.")
    else:
        for i, item in enumerate(resultados["items"], 1):
            print(f"  --- Infraccion {i} ---")
            for clave, valor in item.items():
                print(f"  {clave}: {valor}")
    print("===================================================\n")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
