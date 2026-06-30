"""
Lock y ruta compartidos para la creacion de instancias de undetected_chromedriver.

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
del driver baja a ~1s.
"""

import os
import threading

LOCK_CHROMEDRIVER = threading.Lock()

_RUTA_CACHE = os.path.join(os.environ.get("APPDATA", ""), "undetected_chromedriver", "undetected_chromedriver.exe")
RUTA_CHROMEDRIVER = _RUTA_CACHE if os.path.exists(_RUTA_CACHE) else None
