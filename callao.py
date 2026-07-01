#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de papeletas por PLACA en la Municipalidad del Callao.
Resuelve el captcha de 3 digitos con OCR (aislando el texto azul del
fondo con ruido y leyendo cada captcha en un canvas limpio).
"""

import argparse
import base64
import json
import platform
import re
import sys
import time
import os
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
import pytesseract
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from navegador import LOCK_CHROMEDRIVER, CHROME_VERSION_MAIN, ruta_chromedriver, SEMAFORO_CHROME

URL = "https://pagopapeletascallao.pe/"

INPUT_PLACA_ID = "valor_busqueda"
INPUT_CAPTCHA_ID = "captcha"
BOTON_BUSCAR_ID = "idBuscar"

MAX_INTENTOS_CAPTCHA = 6

# En Windows no esta en el PATH por defecto, hay que apuntar al ejecutable.
# En Linux (contenedor) tesseract-ocr se instala via apt y ya queda en el PATH.
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_driver(headless: bool = False):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=es-PE")

    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, driver_executable_path=ruta_chromedriver(), version_main=CHROME_VERSION_MAIN)
    driver.set_page_load_timeout(60)
    return driver


def _leer_captcha_b64(driver) -> str:
    img_el = driver.find_element(By.CSS_SELECTOR, 'img[alt="captcha"]')
    src = img_el.get_attribute("src")
    return src.split(",", 1)[1]


def resolver_captcha(driver):
    """Decodifica el captcha (3 digitos azules sobre fondo con ruido) y lo lee con OCR.
    Devuelve el string de digitos o None si no se pudo segmentar en 3 partes.
    """
    png_bytes = base64.b64decode(_leer_captcha_b64(driver))
    arr = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    # El texto es azul; el ruido de fondo es gris/blanco. Aislamos el canal azul.
    b, g, r = cv2.split(img)
    azul = cv2.subtract(b, cv2.max(r, g))
    _, binaria = cv2.threshold(azul, 35, 255, cv2.THRESH_BINARY)

    contornos, _ = cv2.findContours(binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cajas = [cv2.boundingRect(c) for c in contornos if cv2.boundingRect(c)[2] * cv2.boundingRect(c)[3] >= 15]
    cajas.sort(key=lambda c: c[0])

    if len(cajas) != 3:
        return None

    # Redibujamos los 3 digitos ya limpios sobre un canvas blanco: el OCR de
    # una linea reconstruida es mucho mas fiable que leer cada digito aislado.
    escala = 6
    pad = 20
    alto_max = max(h for (_, _, _, h) in cajas) * escala
    ancho_total = sum(w for (_, _, w, _) in cajas) * escala + pad * (len(cajas) + 1)
    canvas = np.zeros((alto_max + pad * 2, ancho_total), dtype=np.uint8)

    x_cursor = pad
    for (x, y, w, h) in cajas:
        recorte = binaria[y:y + h, x:x + w]
        recorte = cv2.resize(recorte, (w * escala, h * escala), interpolation=cv2.INTER_CUBIC)
        canvas[pad:pad + h * escala, x_cursor:x_cursor + w * escala] = recorte
        x_cursor += w * escala + pad

    canvas_inv = cv2.bitwise_not(canvas)  # tesseract prefiere texto negro sobre blanco
    config = "--psm 8 -c tessedit_char_whitelist=0123456789"
    texto = pytesseract.image_to_string(canvas_inv, config=config)
    digitos = "".join(ch for ch in texto if ch.isdigit())

    return digitos if len(digitos) == 3 else None


def extraer_resultados(driver):
    resultados = {
        "total_web": "0.00",
        "items": [],
        "suma_calculada": "0.00",
        "sin_resultados": False,
    }

    try:
        total_el = driver.find_element(By.ID, "suma-valores")
        numeros = re.findall(r"\d[\d,]*\.\d+", total_el.text)
        if numeros:
            resultados["total_web"] = numeros[0]
    except NoSuchElementException:
        pass

    try:
        driver.find_element(By.CSS_SELECTOR, ".table-responsive .alert-info")
        resultados["sin_resultados"] = True
        return resultados
    except NoSuchElementException:
        pass

    try:
        tabla = driver.find_element(By.ID, "dataTable")
        headers = [th.text.strip().lower() for th in tabla.find_elements(By.CSS_SELECTOR, "thead th")]

        # Solo nos interesan estas 3 columnas de la tabla (Codigo, Fecha Infraccion, Total)
        idx_codigo = next((i for i, h in enumerate(headers) if "digo" in h), None)
        idx_fecha = next((i for i, h in enumerate(headers) if "fecha" in h), None)
        idx_total = next((i for i, h in enumerate(headers) if h == "total"), None)

        suma = 0.0
        for fila in tabla.find_elements(By.CSS_SELECTOR, "tbody tr"):
            celdas = [td.text.strip() for td in fila.find_elements(By.TAG_NAME, "td")]
            if not celdas:
                continue

            codigo = celdas[idx_codigo] if idx_codigo is not None and idx_codigo < len(celdas) else ""
            fecha = celdas[idx_fecha] if idx_fecha is not None and idx_fecha < len(celdas) else ""
            total_raw = celdas[idx_total] if idx_total is not None and idx_total < len(celdas) else ""

            # La celda de Total puede traer un "*" de descuento pegado (ej: "145.20\n*")
            match_total = re.search(r"\d[\d,]*\.\d+", total_raw)
            total = match_total.group(0) if match_total else "0.00"

            resultados["items"].append({"Codigo": codigo, "Fecha": fecha, "Total": total})

            try:
                suma += float(total.replace(",", ""))
            except ValueError:
                pass

        resultados["suma_calculada"] = f"{suma:,.2f}"
    except NoSuchElementException:
        pass

    return resultados


def consultar(placa: str, headless: bool = True, max_intentos: int = MAX_INTENTOS_CAPTCHA):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    SEMAFORO_CHROME.acquire()
    driver = None
    try:
        driver = crear_driver(headless=headless)
        for intento in range(1, max_intentos + 1):
            driver.get(URL)
            time.sleep(2)

            codigo = resolver_captcha(driver)
            if not codigo:
                print(f"  -> [Intento {intento}] No se pudo leer el captcha, reintentando...")
                continue

            driver.find_element(By.ID, INPUT_PLACA_ID).clear()
            driver.find_element(By.ID, INPUT_PLACA_ID).send_keys(placa)
            driver.find_element(By.ID, INPUT_CAPTCHA_ID).clear()
            driver.find_element(By.ID, INPUT_CAPTCHA_ID).send_keys(codigo)
            driver.find_element(By.ID, BOTON_BUSCAR_ID).click()
            time.sleep(3)

            qs = parse_qs(urlparse(driver.current_url).query)
            if "error" in qs:
                print(f"  -> [Intento {intento}] Captcha '{codigo}' incorrecto, reintentando...")
                continue

            print(f"  -> Captcha resuelto en el intento {intento} ('{codigo}').")
            return extraer_resultados(driver)

        raise RuntimeError(f"No se pudo resolver el captcha tras {max_intentos} intentos.")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
        SEMAFORO_CHROME.release()


def main():
    parser = argparse.ArgumentParser(description="Consulta de papeletas por placa - Municipalidad del Callao")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--headless", action="store_true", default=True, help="Sin ventana (por defecto activado)")
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

    print(f"\n===== RESULTADOS PARA LA PLACA {normalizar_placa(args.placa)} =====")
    if resultados["sin_resultados"] or not resultados["items"]:
        print("  No hay papeletas registradas para esta placa.")
    else:
        for i, item in enumerate(resultados["items"], 1):
            print(f"  --- Papeleta {i} ---")
            print(f"  Codigo: {item['Codigo']}")
            print(f"  Fecha : {item['Fecha']}")
            print(f"  Total : S/ {item['Total']}")
        print(f"\n  -> Suma de papeletas: S/ {resultados['suma_calculada']}")
    print("===================================================\n")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()

