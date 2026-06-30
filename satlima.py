#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de papeletas e impuestos vehiculares por PLACA en SAT Lima.
Extracción directa de Totales para evitar filas ocultas duplicadas.

El reCAPTCHA se resuelve con el servicio pago 2Captcha (variable de entorno
TWOCAPTCHA_API_KEY, leida desde el .env del proyecto): se envia el sitekey
de la pagina y se inyecta el token resuelto directamente en el campo oculto
del widget. La pagina valida el captcha vía grecaptcha.getResponse(), que
lee ese mismo campo, asi que no hace falta interactuar con el checkbox ni
abrir el navegador de forma visible.
"""

import argparse
import json
import re
import sys
import time
import os

import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from navegador import LOCK_CHROMEDRIVER, CHROME_VERSION_MAIN, ruta_chromedriver

URL = "https://www.sat.gob.pe/pagosenlinea/"

SELECT_TIPO_ID = "strTipDoc"
INPUT_DATO_ID = "strNumDoc"
PLACA_VALUE = "3"

TWOCAPTCHA_IN_URL = "https://2captcha.com/in.php"
TWOCAPTCHA_RES_URL = "https://2captcha.com/res.php"


def _cargar_env():
    """Carga variables del .env del proyecto (si existe) sin depender de
    python-dotenv. No pisa variables ya definidas en el entorno real."""
    ruta_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(ruta_env):
        return
    with open(ruta_env, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            os.environ.setdefault(clave.strip(), valor.strip())


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def limpiar_texto_monto(texto: str) -> str:
    """Extrae solo el número de textos como 'TOTAL:   S/ 2,767.00'"""
    # Busca todo lo que sea dígito, coma o punto
    numeros = re.findall(r'[\d\.,]+', texto)
    return numeros[0] if numeros else "0.00"


def crear_driver(headless: bool = True):
    options = uc.ChromeOptions()
    options.page_load_strategy = "eager"
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


def obtener_sitekey(driver) -> str:
    sitekey = driver.execute_script(
        "var el = document.querySelector('[data-sitekey]');"
        "return el ? el.getAttribute('data-sitekey') : null;"
    )
    if sitekey:
        return sitekey

    # Respaldo: el sitekey tambien viaja en la URL del iframe del checkbox.
    try:
        iframe = driver.find_element(By.XPATH, "//iframe[contains(@src, 'recaptcha') and contains(@src, 'anchor')]")
        match = re.search(r"[?&]k=([^&]+)", iframe.get_attribute("src") or "")
        if match:
            return match.group(1)
    except Exception:
        pass

    raise RuntimeError("No se pudo obtener el sitekey del reCAPTCHA de SAT Lima.")


def resolver_recaptcha_2captcha(sitekey: str, page_url: str, timeout: int = 150) -> str:
    """Resuelve un reCAPTCHA v2 con 2Captcha y devuelve el token listo
    para inyectar en el campo g-recaptcha-response de la pagina."""
    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        raise RuntimeError("Falta TWOCAPTCHA_API_KEY (definila en el .env del proyecto).")

    resp = requests.post(TWOCAPTCHA_IN_URL, data={
        "key": api_key,
        "method": "userrecaptcha",
        "googlekey": sitekey,
        "pageurl": page_url,
        "json": 1,
    }, timeout=30)
    datos = resp.json()
    if datos.get("status") != 1:
        raise RuntimeError(f"2Captcha rechazó la solicitud: {datos.get('request')}")

    captcha_id = datos["request"]
    print(f"  ->Captcha enviado a 2Captcha (id={captcha_id}), esperando resolución...")

    time.sleep(15)  # 2Captcha tarda al menos ~15s en resolver un reCAPTCHA
    inicio = time.time()
    while time.time() - inicio < timeout:
        resp = requests.get(TWOCAPTCHA_RES_URL, params={
            "key": api_key,
            "action": "get",
            "id": captcha_id,
            "json": 1,
        }, timeout=30)
        datos = resp.json()

        if datos.get("status") == 1:
            print("  ->Captcha resuelto por 2Captcha.")
            return datos["request"]

        if datos.get("request") != "CAPCHA_NOT_READY":
            raise RuntimeError(f"2Captcha devolvió un error: {datos.get('request')}")

        time.sleep(5)

    raise RuntimeError("2Captcha no devolvió el resultado a tiempo.")


def inyectar_token_captcha(driver, token: str):
    driver.execute_script(
        "var el = document.getElementById('g-recaptcha-response');"
        "if (el) { el.style.display = 'block'; el.innerHTML = arguments[0]; el.value = arguments[0]; }",
        token,
    )


def clic_buscar(driver, wait):
    print("  ->Haciendo clic en el botón Buscar...")
    boton = wait.until(EC.presence_of_element_located((
        By.XPATH,
        "//button[@onclick='BuscarContribuyentes()']"
    )))
    driver.execute_script("arguments[0].click();", boton)


def confirmar_busqueda(driver, wait, timeout: int = 20) -> bool:
    """Hace clic en Buscar y confirma que la tabla de resultados (Paso3)
    realmente cargó. Con internet lento el envío del formulario puede no
    completarse a tiempo aunque el captcha haya sido valido; esto lo
    detecta para no devolver un resultado vacío como si fuera válido.
    """
    clic_buscar(driver, wait)
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.ID, "Paso3")))
        time.sleep(2)
        return True
    except TimeoutException:
        print("  ->No se confirmó la carga de resultados (timeout).")
        return False


def extraer_resultados(driver):
    resultados = {
        "impuesto_vehicular": {"total_web": "0.00"},
        "multas_tributarias": {"total_web": "0.00"},
        "papeletas": {"items": [], "total_web": "0.00"}
    }

    print("  ->Extrayendo datos robustos y comprobando totales...")

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


def consultar(placa: str, headless: bool = True):
    """Consulta SAT Lima. Corre oculto (headless) siempre: el reCAPTCHA se
    resuelve via 2Captcha (sitekey + URL -> token), sin necesidad de
    interactuar con el widget ni de intervencion humana.
    """
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa está vacía.")

    _cargar_env()

    driver = crear_driver(headless=headless)
    wait = WebDriverWait(driver, 15)
    try:
        _preparar_busqueda(driver, wait, placa)

        sitekey = obtener_sitekey(driver)
        token = resolver_recaptcha_2captcha(sitekey, URL)
        inyectar_token_captcha(driver, token)

        if not confirmar_busqueda(driver, wait):
            raise RuntimeError("No se pudo completar la consulta de SAT Lima (timeout de red o captcha rechazado).")

        return extraer_resultados(driver)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Consulta papeletas e impuestos por placa en SAT Lima")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--ver-navegador", action="store_true", help="Mostrar la ventana de Chrome")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    args = parser.parse_args()

    try:
        resultados = consultar(args.placa, headless=not args.ver_navegador)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    tiene_impuestos = resultados["impuesto_vehicular"]["total_web"] != "0.00"
    tiene_multas = resultados["multas_tributarias"]["total_web"] != "0.00"
    tiene_papeletas = resultados["papeletas"]["total_web"] != "0.00"

    if not tiene_impuestos and not tiene_multas and not tiene_papeletas:
        print(f"\nNo se encontraron deudas para la placa {normalizar_placa(args.placa)}.")
        sys.stdout.flush()
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
    sys.stdout.flush()
    os._exit(0)
