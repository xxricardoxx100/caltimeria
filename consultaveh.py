#!/usr/bin/env python3
import os
import re
import time
import warnings

import requests

warnings.filterwarnings("ignore")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TWOCAPTCHA_KEY = os.getenv("TWOCAPTCHA_API_KEY", "")
SITEKEY = "0x4AAAAAACFzt4Xn8T1Jg9ZS"
PAGE_URL = "https://consultavehicular.sunarp.gob.pe/consulta-vehicular/inicio"
API_BASE = "https://api-gateway.sunarp.gob.pe:9443/sunarp/multiservicios"
API_ID = "70574c7d9194834316a156b1d68fdb90"


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[\s\-]", "", placa).upper()


def resolver_turnstile() -> str:
    r = requests.post(
        "http://2captcha.com/in.php",
        data={
            "key": TWOCAPTCHA_KEY,
            "method": "turnstile",
            "sitekey": SITEKEY,
            "pageurl": PAGE_URL,
        },
        timeout=15,
    )
    r.raise_for_status()
    resp = r.text.strip()
    if not resp.startswith("OK|"):
        raise RuntimeError(f"2Captcha submit error: {resp}")
    task_id = resp.split("|", 1)[1]

    for _ in range(30):
        time.sleep(5)
        r2 = requests.get(
            "http://2captcha.com/res.php",
            params={"key": TWOCAPTCHA_KEY, "action": "get", "id": task_id},
            timeout=10,
        )
        text = r2.text.strip()
        if text == "CAPCHA_NOT_READY":
            continue
        if text.startswith("OK|"):
            return text.split("|", 1)[1]
        raise RuntimeError(f"2Captcha result error: {text}")
    raise RuntimeError("2Captcha timeout after 150s")


def consultar(placa: str) -> dict:
    placa = normalizar_placa(placa)
    if not placa:
        raise ValueError("La placa esta vacia.")

    token = resolver_turnstile()

    r = requests.post(
        f"{API_BASE}/multiservicio-consvehicular/consulta/getDatosVehiculo",
        headers={
            "X-IBM-Client-Id": API_ID,
            "Content-Type": "application/json",
        },
        json={
            "numPlaca": placa,
            "regPubId": None,
            "oficRegId": None,
            "ipAddress": "0.0.0.0",
            "appVersion": "1.0",
            "dG9rZW4": token,
        },
        timeout=30,
        verify=False,
    )
    r.raise_for_status()
    data = r.json()

    if data.get("cod") != 1:
        return {"sin_resultados": True}

    imagen_b64 = (data.get("model") or {}).get("imagen")
    if not imagen_b64:
        return {"sin_resultados": True}

    return {"imagen_b64": imagen_b64, "sin_resultados": False}


def main():
    import argparse
    import base64
    import sys

    parser = argparse.ArgumentParser(description="Consulta Vehicular SUNARP")
    parser.add_argument("placa")
    args = parser.parse_args()

    try:
        resultado = consultar(args.placa)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    if resultado.get("sin_resultados"):
        print("Sin informacion para esta placa.")
    else:
        fname = f"sunarp_{args.placa}.png"
        with open(fname, "wb") as f:
            f.write(base64.b64decode(resultado["imagen_b64"]))
        print(f"Imagen guardada: {fname}")


if __name__ == "__main__":
    main()
