#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de infracciones por PLACA en ATU (Autoridad de Transporte Urbano
para Lima y Callao). No requiere captcha.
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
from selenium.common.exceptions import NoSuchElementException

URL = "https://pasarela.atu.gob.pe/"

SELECT_TIPO_ID = "TipoBusquedaselectElemento"
INPUT_PLACA_ID = "PlacaBusquedainputElemento"
TIPO_BUSQUEDA_PLACA_VALUE = "2"


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_driver(headless: bool = True):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=es-PE")

    driver = uc.Chrome(options=options, version_main=149)
    return driver


def ir_a_consulta_infracciones(driver, wait):
    link = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//p[@title='Consulta y Pago de Infracciones']/ancestor::a")
    ))
    driver.execute_script("arguments[0].click();", link)
    wait.until(EC.presence_of_element_located((By.ID, SELECT_TIPO_ID)))
    time.sleep(1)


def seleccionar_busqueda_por_placa(driver, wait):
    select_el = wait.until(EC.presence_of_element_located((By.ID, SELECT_TIPO_ID)))
    driver.execute_script(
        "arguments[0].value = arguments[1];"
        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
        select_el, TIPO_BUSQUEDA_PLACA_VALUE,
    )
    time.sleep(1)


def extraer_resultados(driver):
    resultados = {
        "items": [],
        "suma_calculada": "0.00",
        "sin_resultados": False,
    }

    try:
        mensaje = driver.find_element(By.CSS_SELECTOR, ".swal2-html-container").text.strip()
        if "no cuenta con infracci" in mensaje.lower():
            resultados["sin_resultados"] = True
            try:
                driver.find_element(By.CSS_SELECTOR, ".swal2-confirm").click()
            except NoSuchElementException:
                pass
            return resultados
    except NoSuchElementException:
        pass

    try:
        tabla = driver.find_element(By.ID, "tablePrincipal")
        headers = [th.text.strip().lower() for th in tabla.find_elements(By.CSS_SELECTOR, "thead th")]

        idx_codigo = next((i for i, h in enumerate(headers) if "acta fiscaliza" in h), None)
        idx_fecha = next((i for i, h in enumerate(headers) if "fecha infracc" in h), None)
        idx_total = next((i for i, h in enumerate(headers) if h == "total a pagar"), None)

        suma = 0.0
        for fila in tabla.find_elements(By.CSS_SELECTOR, "tbody tr"):
            celdas = [td.text.strip() for td in fila.find_elements(By.TAG_NAME, "td")]
            if not celdas or not any(celdas):
                continue
            if len(celdas) == 1:
                continue  # fila "Sin Registros"

            codigo = celdas[idx_codigo] if idx_codigo is not None and idx_codigo < len(celdas) else ""
            fecha = celdas[idx_fecha] if idx_fecha is not None and idx_fecha < len(celdas) else ""
            total_raw = celdas[idx_total] if idx_total is not None and idx_total < len(celdas) else ""

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

    if not resultados["items"]:
        resultados["sin_resultados"] = True

    return resultados


def consultar(placa: str, headless: bool = True):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    driver = crear_driver(headless=headless)
    wait = WebDriverWait(driver, 15)
    try:
        driver.get(URL)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)

        ir_a_consulta_infracciones(driver, wait)
        seleccionar_busqueda_por_placa(driver, wait)

        campo_placa = wait.until(EC.presence_of_element_located((By.ID, INPUT_PLACA_ID)))
        campo_placa.clear()
        campo_placa.send_keys(placa)

        boton = driver.find_element(By.CSS_SELECTOR, "#formBusqueda button[type=submit]")
        driver.execute_script("arguments[0].click();", boton)
        time.sleep(3)

        return extraer_resultados(driver)
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Consulta de infracciones por placa - ATU")
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

    print(f"\n===== RESULTADOS PARA LA PLACA {normalizar_placa(args.placa)} =====")
    if resultados["sin_resultados"] or not resultados["items"]:
        print("  No se encontraron infracciones registradas para esta placa.")
    else:
        for i, item in enumerate(resultados["items"], 1):
            print(f"  --- Infraccion {i} ---")
            print(f"  Codigo: {item['Codigo']}")
            print(f"  Fecha : {item['Fecha']}")
            print(f"  Total : S/ {item['Total']}")
        print(f"\n  -> Suma de infracciones: S/ {resultados['suma_calculada']}")
    print("===================================================\n")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
