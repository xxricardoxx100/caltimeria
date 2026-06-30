#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consulta de Certificados de Inspeccion Tecnica Vehicular (CITV) por PLACA en el MTC.
Tiene captcha de 6 digitos, resuelto con pytesseract. No requiere navegador: todo el
flujo se hace por HTTP directo contra el backend del portal (rec.mtc.gob.pe).
"""

import argparse
import base64
import json
import platform
import re
import sys
import os

import cv2
import numpy as np
import pytesseract
import requests

URL_PAGINA = "https://rec.mtc.gob.pe/Citv/ArConsultaCitv"
URL_CAPTCHA = "https://rec.mtc.gob.pe/CITV/refrescarCaptcha"
URL_BUSCAR = "https://rec.mtc.gob.pe/CITV/JrCITVConsultarFiltro"

if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def crear_sesion():
    sesion = requests.Session()
    sesion.headers.update({"User-Agent": "Mozilla/5.0"})
    sesion.get(URL_PAGINA, timeout=20)
    return sesion


def resolver_captcha(sesion):
    r = sesion.get(URL_CAPTCHA, timeout=20)
    data = r.json()
    raw = base64.b64decode(data["orResult"])
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    config = "--psm 8 -c tessedit_char_whitelist=0123456789"
    texto = pytesseract.image_to_string(binary, config=config).strip().replace(" ", "").replace("\n", "")
    return texto


def buscar(sesion, placa, captcha):
    parametros = f"1|{placa}||{captcha}"
    r = sesion.get(URL_BUSCAR, params={"pArrParametros": parametros}, timeout=20)
    return r.json()


def consultar(placa: str, max_intentos: int = 15):
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    sesion = crear_sesion()

    for _ in range(max_intentos):
        texto = resolver_captcha(sesion)
        if len(texto) != 6:
            continue

        data = buscar(sesion, placa, texto)

        if data.get("orCodigo") == "-1":
            continue  # captcha incorrecto, se reintenta con uno nuevo

        if not data.get("orStatus"):
            raise RuntimeError("Ocurrio un error al consultar el servicio del MTC.")

        registros = json.loads(data["orResult"][0])
        return registros

    raise RuntimeError("No se pudo resolver el captcha tras varios intentos.")


def main():
    parser = argparse.ArgumentParser(description="Consulta de CITV (revision tecnica) por placa - MTC")
    parser.add_argument("placa", help="Placa a consultar (ej: ABC123)")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    args = parser.parse_args()

    try:
        registros = consultar(args.placa)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

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
