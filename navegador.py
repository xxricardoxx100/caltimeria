"""
Lock y helpers compartidos para la creacion de instancias de undetected_chromedriver.

La primera vez que se usa, undetected_chromedriver parchea y copia su
ejecutable en %appdata%\\undetected_chromedriver. Si dos scripts crean un
driver al mismo tiempo (ej. varias consultas en paralelo desde app.py),
ambos intentan escribir ese mismo archivo y uno falla con
WinError 183 (no se puede crear un archivo que ya existe). Serializamos
solo el arranque del navegador para evitar la condicion de carrera; el
resto de la consulta sigue corriendo en paralelo.

Ademas, si no se le indica una ruta de ejecutable explicita, uc.Chrome()
borra y vuelve a descargar/parchear el chromedriver en CADA llamada
(ver Patcher.auto() en patcher.py), lo que agrega ~45s por consulta.
Pasando driver_executable_path hacia el binario ya cacheado, uc.Chrome()
toma el camino rapido (solo verifica que ya este parcheado) y la creacion
del driver baja a ~1s. La ruta se evalua en cada llamada (no una sola vez
al importar el modulo) porque en un contenedor recien iniciado el cache
todavia no existe en el primer arranque.
"""

import os
import platform
import re
import subprocess
import threading

LOCK_CHROMEDRIVER = threading.Lock()


def _ruta_cache_chromedriver():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", "")
        nombre = "undetected_chromedriver.exe"
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
        nombre = "undetected_chromedriver"
    return os.path.join(base, "undetected_chromedriver", nombre)


def ruta_chromedriver():
    ruta = _ruta_cache_chromedriver()
    return ruta if os.path.exists(ruta) else None


def _detectar_chrome_version_main():
    """Version mayor del Chrome instalado, o None para dejar que
    undetected_chromedriver la autodetecte (funciona bien en Windows).
    En el contenedor Linux esa autodeteccion fallo y descargo un
    chromedriver desincronizado del Chrome real instalado via apt, asi
    que aca se la fuerza explicitamente consultando el binario."""
    for cmd in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        try:
            salida = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, timeout=5
            ).stdout
        except (FileNotFoundError, OSError):
            continue
        match = re.search(r"(\d+)\.", salida)
        if match:
            return int(match.group(1))
    return None


CHROME_VERSION_MAIN = _detectar_chrome_version_main()
