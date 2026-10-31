"""ExifTool en modo stay_open: un solo proceso para miles de lecturas/escrituras."""
import json
import subprocess
import threading

from .config import EXIFTOOL

_SENTINEL = "{ready}"


class ExifTool:
    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *_):
        self.cerrar()

    def abrir(self):
        if self._proc:
            return
        self._proc = subprocess.Popen(
            [EXIFTOOL, "-stay_open", "True", "-@", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def cerrar(self):
        if self._proc:
            self._proc.stdin.write(b"-stay_open\nFalse\n")
            self._proc.stdin.flush()
            self._proc.wait(timeout=30)
            self._proc = None

    def ejecutar(self, *args: str) -> str:
        """Ejecuta un comando y devuelve stdout."""
        self.abrir()
        lineas = ["-charset", "filename=utf8", *args, "-execute"]
        with self._lock:
            self._proc.stdin.write(("\n".join(lineas) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            salida = bytearray()
            while not salida.rstrip().endswith(_SENTINEL.encode()):
                trozo = self._proc.stdout.read1(65536)
                if not trozo:
                    break
                salida += trozo
        return salida.decode("utf-8", "replace").rstrip()[: -len(_SENTINEL)].strip()

    def leer(self, archivos, *etiquetas: str) -> list[dict]:
        """Lee metadatos de uno o varios archivos como lista de dicts."""
        archivos = [str(a) for a in archivos]
        if not archivos:
            return []
        salida = self.ejecutar("-json", "-n", *etiquetas, *archivos)
        return json.loads(salida) if salida else []

    def escribir(self, archivo, *asignaciones: str) -> str:
        """Escribe etiquetas conservando la fecha de modificacion del archivo."""
        return self.ejecutar("-overwrite_original", "-P", *asignaciones, str(archivo))


