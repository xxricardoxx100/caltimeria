#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta Vehicular en SUNARP.
Llena la placa, espera el checkbox automatico, busca y devuelve screenshot del resultado.
"""

import argparse
import base64
import platform
import re
import subprocess
import sys
import os
import time

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from navegador import LOCK_CHROMEDRIVER, CHROME_VERSION_MAIN, ruta_chromedriver

URL = "https://consultavehicular.sunarp.gob.pe/consulta-vehicular/inicio"

# En Linux iniciamos un display virtual para que Chrome no corra headless
# (Cloudflare Turnstile detecta y bloquea Chrome headless)
_xvfb_proc = None
if platform.system() == "Linux":
    _xvfb_proc = subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1280x900x24"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    os.environ.setdefault("DISPLAY", ":99")
    time.sleep(1)


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_driver(headless: bool = True):
    options = uc.ChromeOptions()
    if platform.system() == "Linux":
        # Xvfb proporciona el display — no usamos --headless para bypassear Turnstile
        pass
    elif headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--lang=es-PE")
    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, driver_executable_path=ruta_chromedriver(), version_main=CHROME_VERSION_MAIN)
    driver.set_page_load_timeout(60)
    return driver


def capturar_pagina_completa(driver):
    total_h = driver.execute_script("return document.body.scrollHeight")
    driver.set_window_size(1280, max(900, total_h + 50))
    time.sleep(0.4)
    return driver.get_screenshot_as_png()


def consultar(placa: str, headless: bool = True):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    driver = crear_driver(headless)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get(URL)
        time.sleep(2)

        # Llenar placa
        campo_placa = wait.until(EC.presence_of_element_located((By.ID, "nroPlaca")))
        campo_placa.clear()
        campo_placa.send_keys(placa)

        # Esperar que Cloudflare Turnstile complete la verificacion automatica
        try:
            WebDriverWait(driver, 25).until(
                lambda d: d.find_element(By.NAME, "cf-turnstile-response").get_attribute("value")
            )
        except TimeoutException:
            pass  # si Turnstile no se completa, intentar buscar igual

        # Clic en Realizar Busqueda
        boton = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-sunarp-green")))
        driver.execute_script("arguments[0].click();", boton)

        # Esperar resultado — ant-table o card de resultado
        try:
            wait.until(EC.presence_of_element_located((
                By.CSS_SELECTOR,
                ".ant-table, .ant-card-body, nz-table, [class*='tarjeta'], [class*='tive'], [class*='resultado']"
            )))
        except TimeoutException:
            pass

        time.sleep(2)

        png = capturar_pagina_completa(driver)
        return {"imagen_b64": base64.b64encode(png).decode(), "sin_resultados": False}

    except TimeoutException:
        return {"sin_resultados": True}
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Consulta Vehicular SUNARP por placa")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--ver-navegador", action="store_true")
    args = parser.parse_args()

    try:
        resultado = consultar(args.placa, headless=not args.ver_navegador)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    if resultado.get("sin_resultados"):
        print("Sin informacion para esta placa.")
    else:
        b64 = resultado["imagen_b64"]
        path = f"sunarp_{args.placa}.png"
        with open(path, "wb") as f:
            import base64 as b64mod
            f.write(b64mod.b64decode(b64))
        print(f"Screenshot guardado en: {path}")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
