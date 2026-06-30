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

from navegador import LOCK_CHROMEDRIVER, RUTA_CHROMEDRIVER

URL = "https://www.sat.gob.pe/pagosenlinea/"

SELECT_TIPO_ID = "strTipDoc"
INPUT_DATO_ID = "strNumDoc"
PLACA_VALUE = "3"

# Perfil de Chrome persistente (no temporal). Un perfil nuevo en cada
# ejecucion no tiene cookies ni historial, lo que hace que el scoring de
# riesgo de reCAPTCHA lo trate siempre como "desconocido" y exija el reto
# de imagenes. Reutilizando el mismo perfil entre consultas se acumulan
# cookies de confianza de Google y el checkbox simple vuelve a ser
# suficiente la mayoria de las veces (como pasaba antes).
PERFIL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile_satlima")


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
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-data-dir={PERFIL_DIR}")

    with LOCK_CHROMEDRIVER:
        driver = uc.Chrome(options=options, version_main=149, driver_executable_path=RUTA_CHROMEDRIVER)
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


def _estado_checkbox(driver):
    """Lee aria-checked del checkbox de reCAPTCHA. None si no se pudo leer
    (incluida la sesion del navegador cerrada/crasheada)."""
    try:
        iframe = driver.find_element(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'anchor')]")
        driver.switch_to.frame(iframe)
        estado = driver.find_element(By.ID, "recaptcha-anchor").get_attribute("aria-checked")
        driver.switch_to.default_content()
        return estado
    except Exception:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return None


def _hay_reto_visible(driver):
    """True si Google abrio el iframe del reto de imagenes (bframe)."""
    return bool(driver.find_elements(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'bframe')]"))


def intentar_checkbox(driver, wait, timeout: int = 8) -> bool:
    """Hace clic en el checkbox de reCAPTCHA y espera un momento a ver si
    Google lo deja pasar solo. Devuelve True si quedo resuelto sin reto,
    False si aparecio el reto de imagenes o no se confirmo a tiempo.
    """
    print("\n  → Intentando hacer clic en el checkbox de reCAPTCHA...")
    try:
        iframe = wait.until(EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'anchor')]")))
        driver.switch_to.frame(iframe)
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-anchor")))
        time.sleep(1)
        checkbox.click()
        print("  → ¡Clic en reCAPTCHA realizado!")
        driver.switch_to.default_content()
    except Exception as e:
        print(f"  → [Advertencia] No se pudo automatizar el clic del CAPTCHA: {e}")
        driver.switch_to.default_content()
        return False

    inicio = time.time()
    while time.time() - inicio < timeout:
        if _estado_checkbox(driver) == "true":
            print("  → Checkbox aceptado sin reto adicional.")
            return True
        if _hay_reto_visible(driver):
            print("  → Google esta pidiendo el reto de imagenes.")
            return False
        time.sleep(0.5)

    print("  → El checkbox no se confirmo a tiempo.")
    return False


def esperar_captcha_manual(driver, timeout: int = 90) -> bool:
    print("\n  → Esperando a que resuelvas el captcha manualmente en la ventana de Chrome...")
    inicio = time.time()
    while time.time() - inicio < timeout:
        if _estado_checkbox(driver) == "true":
            print("  → ¡Check verde detectado! Avanzando a buscar...")
            time.sleep(1)
            return True
        time.sleep(1)

    print("  → [Tiempo agotado] El CAPTCHA no se resolvio a tiempo.")
    return False


def clic_buscar(driver, wait):
    print("  → Haciendo clic en el botón Buscar...")
    boton = wait.until(EC.presence_of_element_located((
        By.XPATH,
        "//button[@onclick='BuscarContribuyentes()']"
    )))
    driver.execute_script("arguments[0].click();", boton)


def confirmar_busqueda(driver, wait, timeout: int = 20) -> bool:
    """Hace clic en Buscar y confirma que la tabla de resultados (Paso3)
    realmente cargó. Con internet lento el checkbox puede marcar "pasado"
    pero el envío del formulario no completarse a tiempo; esto lo detecta
    para no devolver un resultado vacío como si fuera válido.
    """
    clic_buscar(driver, wait)
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.ID, "Paso3")))
        time.sleep(2)
        return True
    except TimeoutException:
        print("  → No se confirmó la carga de resultados (timeout).")
        return False


def extraer_resultados(driver):
    resultados = {
        "impuesto_vehicular": {"total_web": "0.00"},
        "multas_tributarias": {"total_web": "0.00"},
        "papeletas": {"items": [], "total_web": "0.00"}
    }

    print("  → Extrayendo datos robustos y comprobando totales...")

    # --- 1. EXTRACCIÓN DE IMPUESTO VEHICULAR (Solo el TOTAL general) ---
    try:
        div_impuestos = driver.find_element(By.ID, "divImpVehicular")
        # Extraemos directamente de la clase montoconcepto sugerida en tu imagen
        total_elem = div_impuestos.find_element(By.CSS_SELECTOR, "div.montoconcepto")
        resultados["impuesto_vehicular"]["total_web"] = limpiar_texto_monto(total_elem.text)
    except Exception:
        pass # No tiene deuda vehicular

    # --- 2. EXTRACCIÓN DE MULTAS TRIBUTARIAS (Solo el TOTAL general) ---
    # Esta sección solo aparece en la página si el vehículo tiene multas
    # tributarias; en orden siempre va después del impuesto vehicular y
    # antes de las papeletas.
    try:
        div_multas = driver.find_element(By.ID, "divMultasTributarias")
        total_elem_multas = div_multas.find_element(By.CSS_SELECTOR, "div.montoconcepto")
        resultados["multas_tributarias"]["total_web"] = limpiar_texto_monto(total_elem_multas.text)
    except Exception:
        pass # No tiene multas tributarias

    # --- 3. EXTRACCIÓN DE PAPELETAS (Items + TOTAL general) ---
    try:
        div_papeletas = driver.find_element(By.ID, "divPapeletas")

        # Extraer el TOTAL de la cabecera
        total_elem_pap = div_papeletas.find_element(By.CSS_SELECTOR, "div.montoconcepto")
        resultados["papeletas"]["total_web"] = limpiar_texto_monto(total_elem_pap.text)

        # Las filas de detalle empiezan ocultas (display:none) hasta que se
        # hace clic en el "+". Selenium .text no lee texto de elementos
        # ocultos, y un clic + sleep fijo es una carrera contra el render;
        # en vez de eso forzamos el display directamente por JS para que
        # la lectura de texto que sigue sea inmediata y confiable.
        driver.execute_script(
            "arguments[0].querySelectorAll('.menu').forEach(function(el){ el.style.display = 'block'; });",
            div_papeletas,
        )

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
def _preparar_busqueda(driver, wait, placa):
    driver.get(URL)
    wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    time.sleep(2)

    seleccionar_placa(driver, wait)
    escribir_placa(driver, wait, placa)


def consultar(placa: str, headless: bool = True, manual_captcha: bool = True):
    """Consulta SAT Lima. Por defecto corre oculto (headless); si el
    checkbox de reCAPTCHA no basta y aparece el reto de imagenes, cierra
    el navegador oculto y reabre uno visible (mismo perfil persistente)
    para que el reto se resuelva a mano, y continua el flujo desde ahi.
    """
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa está vacía.")

    intentos = [headless, False] if headless else [False]

    driver = None
    wait = None
    confirmado = False
    try:
        for i, modo_headless in enumerate(intentos):
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            driver = crear_driver(headless=modo_headless)
            wait = WebDriverWait(driver, 15)

            _preparar_busqueda(driver, wait, placa)
            resuelto = intentar_checkbox(driver, wait)

            es_ultimo_intento = i == len(intentos) - 1
            if not resuelto and es_ultimo_intento and not modo_headless and manual_captcha:
                resuelto = esperar_captcha_manual(driver)

            if resuelto:
                # No basta con que el checkbox marque "pasado": con internet
                # lento el envio del formulario puede fallar igual. Solo
                # damos el intento por bueno si la tabla de resultados
                # realmente carga; si no, escalamos al siguiente intento
                # (oculto -> visible) en vez de devolver un resultado vacio.
                confirmado = confirmar_busqueda(driver, wait)
                if confirmado:
                    break

        if not confirmado:
            raise RuntimeError("No se pudo completar la consulta de SAT Lima (captcha no resuelto o timeout de red).")

        return extraer_resultados(driver)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


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
    tiene_multas = resultados["multas_tributarias"]["total_web"] != "0.00"
    tiene_papeletas = resultados["papeletas"]["total_web"] != "0.00"

    if not tiene_impuestos and not tiene_multas and not tiene_papeletas:
        print(f"\nNo se encontraron deudas para la placa {normalizar_placa(args.placa)}.")
        os._exit(0)

    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
    else:
        print(f"\n===== RESULTADOS PARA LA PLACA {normalizar_placa(args.placa)} =====")

        if tiene_impuestos:
            print(f"\n[ IMPUESTO VEHICULAR ]")
            print(f"  -> Total Adeudado (según web): S/ {resultados['impuesto_vehicular']['total_web']}")

        if tiene_multas:
            print(f"\n[ MULTAS TRIBUTARIAS ]")
            print(f"  -> Total Adeudado (según web): S/ {resultados['multas_tributarias']['total_web']}")

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