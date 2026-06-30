"""
Lock compartido para la creacion de instancias de undetected_chromedriver.

La primera vez que se usa, undetected_chromedriver parchea y copia su
ejecutable en %appdata%\\undetected_chromedriver. Si dos scripts crean un
driver al mismo tiempo (ej. varias consultas en paralelo desde app.py),
ambos intentan escribir ese mismo archivo y uno falla con
WinError 183 (no se puede crear un archivo que ya existe). Serializamos
solo el arranque del navegador para evitar la condicion de carrera; el
resto de la consulta sigue corriendo en paralelo.
"""

import threading

LOCK_CHROMEDRIVER = threading.Lock()
