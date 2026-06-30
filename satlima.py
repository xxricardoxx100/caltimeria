#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de papeletas e impuestos vehiculares por PLACA en SAT Lima.
Extracción directa de Totales para evitar filas ocultas duplicadas.
"""

import argparse
import json
import re
import sys
import time
import os

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from navegador import LOCK_CHROMEDRIVER

URL = "https://www.sat.gob.pe/pagosenlinea/"

SELECT_TIPO_ID = "strTipDoc"
INPUT_DATO_ID = "strNumDoc"
PLACA_VALUE = "3"


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def limpiar_texto_monto(texto: str) -> str:
    """Extrae solo el número de textos como 'TOTAL:   S/ 2,767.00'"""
    # Busca todo lo que sea dígito, coma o punto
    numeros = re.findall(r'[\d\.,]+', texto)
    return numeros[0] if numeros else "0.00"


def crear_driver(headless: bool = False):
    options = uc.ChromeOptions()
    if headless:
        options.add_argument('--headless')
        
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--lang=es-PE")

    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, version_main=149)
    return driver


def seleccionar_placa(driver, wait):
    select_el = wait.until(EC.presence_of_element_located((By.ID, SELECT_TIPO_ID)))
    Select(select_el).select_by_value(PLACA_VALUE)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
        select_el,
    )
    time.sleep(0.5)


def escribir_placa(driver, wait, placa: str):
    campo = wait.until(EC.presence_of_element_located((By.ID, INPUT_DATO_ID)))
    driver.execute_script("arguments[0].removeAttribute('maxlength');", campo)
    campo.clear()
    campo.send_keys(placa)

    actual = campo.get_attribute("value") or ""
    if actual.upper() != placa.upper():
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            campo, placa,
        )


def procesar_captcha(driver, wait, manual: bool):
    print("\n  → Intentando hacer clic en el checkbox de reCAPTCHA...")
    try:
        iframe = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'recaptcha')]")))
        driver.switch_to.frame(iframe)
        
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-anchor")))
        time.sleep(1)
        checkbox.click()
        print("  → ¡Clic en reCAPTCHA realizado!")
        
        driver.switch_to.default_content()
    except Exception as e:
        print(f"  → [Advertencia] No se pudo automatizar el clic del CAPTCHA: {e}")
        driver.switch_to.default_content()

    if not manual:
        return
        
    print("\n  → Vigilando el CAPTCHA automáticamente...")
    timeout = 60
    inicio = time.time()
    
    while time.time() - inicio < timeout:
        try:
            iframe = driver.find_element(By.XPATH, "//iframe[contains(@src, 'recaptcha')]")
            driver.switch_to.frame(iframe)
            estado = driver.find_element(By.ID, "recaptcha-anchor").get_attribute("aria-checked")
            driver.switch_to.default_content()
            
            if estado == "true":
                print("  → ¡Check verde detectado! Avanzando a buscar...")
                time.sleep(1)
                return
        except:
            driver.switch_to.default_content()
        
        time.sleep(1)
        
    print("  → [Tiempo agotado] El CAPTCHA no se puso en verde después de 60 segundos.")


def clic_buscar(driver, wait):
    print("  → Haciendo clic en el botón Buscar...")
    boton = wait.until(EC.presence_of_element_located((
        By.XPATH,
        "//button[@onclick='BuscarContribuyentes()']"
    )))
    driver.execute_script("arguments[0].click();", boton)


def extraer_resultados(driver, wait):
    resultados = {
        "impuesto_vehicular": {"total_web": "0.00"},
        "papeletas": {"items": [], "total_web": "0.00"}
    }

    try:
        wait.until(EC.presence_of_element_located((By.ID, "Paso3")))
        time.sleep(2) 
    except TimeoutException:
        print("  → No se detectó la tabla de resultados.")
        return resultados

    print("  → Extrayendo datos robustos y comprobando totales...")

    # --- 1. EXTRACCIÓN DE IMPUESTO VEHICULAR (Solo el TOTAL general) ---
    try:
        div_impuestos = driver.find_element(By.ID, "divImpVehicular")
        # Extraemos directamente de la clase montoconcepto sugerida en tu imagen
        total_elem = div_impuestos.find_element(By.CSS_SELECTOR, "div.montoconcepto")
        resultados["impuesto_vehicular"]["total_web"] = limpiar_texto_monto(total_elem.text)
    except Exception:
        pass # No tiene deuda vehicular

    # --- 2. EXTRACCIÓN DE PAPELETAS (Items + TOTAL general) ---
    try:
        div_papeletas = driver.find_element(By.ID, "divPapeletas")
        
        # Extraer el TOTAL de la cabecera
        total_elem_pap = div_papeletas.find_element(By.CSS_SELECTOR, "div.montoconcepto")
        resultados["papeletas"]["total_web"] = limpiar_texto_monto(total_elem_pap.text)

        # Desplegar para leer las filas (solo dentro de papeletas para evitar basura)
        botones_plus = div_papeletas.find_elements(By.CSS_SELECTOR, "i.fa-plus")
        for btn in botones_plus:
            try:
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.2)
            except:
                pass

        # Leer filas de papeletas
        filas_pap = div_papeletas.find_elements(By.CSS_SELECTOR, "div.row.gridtree-row[data-id]")
        for fila in filas_pap:
            try:
                falta_elem = fila.find_element(By.XPATH, ".//div[contains(@class, 'text-left') and contains(@class, 'item-center')]")
                falta = falta_elem.text.strip().replace("\n", " ")
                
                fecha = "No encontrada"
                columnas_centradas = fila.find_elements(By.CSS_SELECTOR, "div.item-center")
                for col in columnas_centradas:
                    texto = col.text.strip()
                    if "/" in texto and len(texto) == 10:
                        fecha = texto
                        break
                        
                monto_elem = fila.find_element(By.CSS_SELECTOR, "span.monto")
                monto = monto_elem.text.strip()

                resultados["papeletas"]["items"].append({
                    "Falta": falta,
                    "Fecha": fecha,
                    "Monto": monto
                })
            except Exception:
                continue
    except Exception:
        pass # No tiene papeletas

    return resultados
def consultar(placa: str, headless: bool = False, manual_captcha: bool = True):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa está vacía.")

    driver = crear_driver(headless=headless)
    wait = WebDriverWait(driver, 15)
    try:
        driver.get(URL)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2) 

        seleccionar_placa(driver, wait)
        escribir_placa(driver, wait, placa)
        procesar_captcha(driver, wait, manual_captcha and not headless)
        clic_buscar(driver, wait)
        
        print("  → Esperando a que cargue la tabla de resultados...")
        return extraer_resultados(driver, wait)
    finally:
        driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Consulta papeletas e impuestos por placa en SAT Lima")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--headless", action="store_true", help="Sin ventana (puede bajar tu score de confianza)")
    parser.add_argument("--no-captcha-pause", action="store_true", help="No pausar tras el clic automático")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    args = parser.parse_args()

    try:
        resultados = consultar(
            args.placa,
            headless=args.headless,
            manual_captcha=not args.no_captcha_pause,
        )
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        os._exit(1)

    tiene_impuestos = resultados["impuesto_vehicular"]["total_web"] != "0.00"
    tiene_papeletas = resultados["papeletas"]["total_web"] != "0.00"

    if not tiene_impuestos and not tiene_papeletas:
        print(f"\nNo se encontraron deudas para la placa {normalizar_placa(args.placa)}.")
        os._exit(0)

    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
    else:
        print(f"\n===== RESULTADOS PARA LA PLACA {normalizar_placa(args.placa)} =====")
        
        if tiene_impuestos:
            print(f"\n[ IMPUESTO VEHICULAR ]")
            print(f"  -> Total Adeudado (según web): S/ {resultados['impuesto_vehicular']['total_web']}")
                
        if tiene_papeletas:
            items = resultados["papeletas"]["items"]
            print(f"\n[ PAPELETAS ] - {len(items)} registro(s) encontrados:")
            
            suma_calculada = 0.0
            
            for i, r in enumerate(items, 1):
                print(f"  --- Papeleta {i} ---")
                print(f"  Falta: {r['Falta']}")
                print(f"  Fecha: {r['Fecha']}")
                print(f"  Monto: S/ {r['Monto']}")
                
                # Sumar para comprobación (quitando comas si existen)
                valor_limpio = r['Monto'].replace(',', '')
                try:
                    suma_calculada += float(valor_limpio)
                except:
                    pass
            
            print(f"  -----------------------------")
            print(f"  -> Suma de items extraídos   : S/ {suma_calculada:,.2f}")
            print(f"  -> Total Oficial (según web) : S/ {resultados['papeletas']['total_web']}")
            
        print("===================================================\n")


if __name__ == "__main__":
    main()
    os._exit(0)