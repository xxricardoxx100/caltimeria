#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de vigencia de SOAT por PLACA en APESEG.
Tiene captcha de 6 caracteres alfanumericos, resuelto con EasyOCR.
"""

import argparse
import base64
import json
import re
import sys
import time
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="torch")

import cv2
import numpy as np
import easyocr
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from navegador import LOCK_CHROMEDRIVER, CHROME_VERSION_MAIN, ruta_chromedriver

URL = "https://www.apeseg.org.pe/consultas-soat/"
IFRAME_SELECTOR = "iframe[src*='consulta-soat']"
ALLOWLIST = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_reader = None


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_driver(headless: bool = True):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=es-PE")

    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, driver_executable_path=ruta_chromedriver(), version_main=CHROME_VERSION_MAIN)
    driver.set_page_load_timeout(30)
    return driver


def obtener_reader():
    global _reader
    if _reader is None:
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


def resolver_captcha(driver):
    img_el = driver.find_element(By.CSS_SELECTOR, "img.captcha-img")
    src = img_el.get_attribute("src")
    b64 = src.split(",", 1)[1]
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    resultados = obtener_reader().readtext(img, allowlist=ALLOWLIST)
    texto = "".join(r[1] for r in resultados)
    return texto


def ir_al_formulario(driver):
    driver.get(URL)
    time.sleep(3)
    iframe = driver.find_element(By.CSS_SELECTOR, IFRAME_SELECTOR)
    driver.switch_to.frame(iframe)
    time.sleep(2)


def extraer_resultados(driver):
    resultados = {
        "estado": "",
        "vigente": False,
        "inicio": "",
        "fin": "",
        "sin_resultados": False,
    }

    try:
        tabla = driver.find_element(By.CSS_SELECTOR, ".resultados .tabla")
    except NoSuchElementException:
        resultados["sin_resultados"] = True
        return resultados

    datos = {}
    for fila in tabla.find_elements(By.TAG_NAME, "tr"):
        try:
            clave = fila.find_element(By.TAG_NAME, "th").text.strip()
            valor_celda = fila.find_element(By.TAG_NAME, "td")
        except NoSuchElementException:
            continue
        datos[clave] = valor_celda.text.strip()
        if clave == "Estado":
            try:
                span = valor_celda.find_element(By.TAG_NAME, "span")
                resultados["vigente"] = "no-vigente" not in span.get_attribute("class")
            except NoSuchElementException:
                pass

    resultados["estado"] = datos.get("Estado", "")
    resultados["inicio"] = datos.get("Inicio", "")
    resultados["fin"] = datos.get("Fin", "")

    if not resultados["estado"]:
        resultados["sin_resultados"] = True

    return resultados


def consultar(placa: str, headless: bool = True, max_intentos: int = 25):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    driver = crear_driver(headless=headless)
    try:
        ir_al_formulario(driver)

        driver.find_element(By.ID, "placa").send_keys(placa)

        for _ in range(max_intentos):
            texto = resolver_captcha(driver)
            if len(texto) != 6:
                driver.find_element(By.CSS_SELECTOR, "img.captcha-img").click()
                time.sleep(1.5)
                continue

            campo_captcha = driver.find_element(By.ID, "captcha")
            campo_captcha.clear()
            campo_captcha.send_keys(texto)
            driver.find_element(By.CSS_SELECTOR, "button[type=submit]").click()
            time.sleep(2.5)

            try:
                driver.find_element(By.CSS_SELECTOR, ".form-error")
                continue
            except NoSuchElementException:
                return extraer_resultados(driver)

        raise RuntimeError("No se pudo resolver el captcha tras varios intentos.")
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Consulta de vigencia de SOAT por placa - APESEG")
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

    print(f"\n===== SOAT PARA LA PLACA {normalizar_placa(args.placa)} =====")
    if resultados["sin_resultados"]:
        print("  No se encontro informacion de SOAT para esta placa.")
    else:
        print(f"  Estado : {resultados['estado']} ({'VIGENTE' if resultados['vigente'] else 'NO VIGENTE'})")
        print(f"  Inicio : {resultados['inicio']}")
        print(f"  Fin    : {resultados['fin']}")
    print("===================================================\n")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
