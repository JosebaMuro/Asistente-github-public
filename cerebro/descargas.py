"""Primera ejecución: descarga llama.cpp y los modelos de voz.

Los modelos del LLM los descarga el propio llama-server con -hf (caché en ./modelos/llama).
"""
from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path

import httpx

from .config import CONFIG
from .eventos import hub

log = logging.getLogger("cerebro.descargas")

GH_RELEASES = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

MODELOS_VOZ = {
    "asr": (f"{SHERPA}/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2",
            "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"),
    "vad": (f"{SHERPA}/asr-models/silero_vad.onnx", "silero_vad.onnx"),
    "segmentacion": (f"{SHERPA}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2",
                     "sherpa-onnx-pyannote-segmentation-3-0"),
    "huella_voz": (f"{SHERPA}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
                   "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"),
}


def carpeta_voz() -> Path:
    p = CONFIG["rutas"]["modelos"] / "voz"
    p.mkdir(parents=True, exist_ok=True)
    return p


def ruta_modelo_voz(clave: str) -> Path:
    return carpeta_voz() / MODELOS_VOZ[clave][1]


def es_windows() -> bool:
    return platform.system() == "Windows"


def binario_llama() -> Path | None:
    """El llama-server que se usará: el de config, el elegido por el motor o el primero que haya."""
    propio = CONFIG["llama"].get("binario")
    if propio:
        p = Path(propio)
        return p if p.exists() else None
    from .motor import motor  # evita import circular

    if motor.eleccion:
        return motor.eleccion["binario"]
    c = candidatos()
    return c[0] if c else None


def candidatos() -> list[Path]:
    """Todos los llama-server disponibles: incluidos en el paquete y descargados en ./motor."""
    nombre = "llama-server.exe" if es_windows() else "llama-server"
    vistos, lista = set(), []
    for p in [Path(x) for x in CONFIG["llama"].get("incluidos", [])] + sorted(CONFIG["rutas"]["motor"].rglob(nombre)):
        if p.exists() and p.resolve() not in vistos:
            vistos.add(p.resolve())
            lista.append(p)
    en_path = shutil.which("llama-server")
    if en_path and Path(en_path).resolve() not in vistos:
        lista.append(Path(en_path))
    return lista


def gpus() -> list[str]:
    """Fabricantes de las tarjetas gráficas del equipo: nvidia, amd, intel."""
    fab = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
    vistos: list[str] = []
    if es_windows():
        try:
            import subprocess

            salida = subprocess.run(["powershell", "-NoProfile", "-Command",
                                     "(Get-CimInstance Win32_VideoController).Name"],
                                    capture_output=True, text=True, timeout=15,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
            for clave, nombre in (("nvidia", "nvidia"), ("radeon", "amd"), ("amd", "amd"), ("intel", "intel")):
                if clave in salida and nombre not in vistos:
                    vistos.append(nombre)
        except Exception:  # noqa: BLE001
            pass
    else:
        for v in sorted(Path("/sys/class/drm").glob("card*/device/vendor")):
            try:
                n = fab.get(v.read_text().strip())
            except OSError:
                continue
            if n and n not in vistos:
                vistos.append(n)
    return vistos


def variante() -> str:
    """Qué llama.cpp descargar si no hay ninguno incluido: cuda | rocm | vulkan | cpu."""
    v = (CONFIG["llama"].get("variante") or "auto").lower()
    if v != "auto":
        return v
    g = gpus()
    if "nvidia" in g or shutil.which("nvidia-smi"):
        return "cuda" if es_windows() else "vulkan"
    if "amd" in g:
        return "rocm"
    if g or es_windows() or shutil.which("vulkaninfo"):
        return "vulkan"
    return "cpu"


def _patrones(v: str) -> list[tuple[str, str | None]]:
    """(patrón del binario, patrón de librerías extra) por orden de preferencia."""
    if es_windows():
        orden = {
            "cuda": [(r"bin-win-cuda-12[\d.]*-x64\.zip$", r"^cudart-.*win-cuda-12[\d.]*-x64\.zip$"),
                     (r"bin-win-vulkan-x64\.zip$", None)],
            "rocm": [(r"bin-win-(rocm|hip)[-\w.]*-x64\.zip$", None), (r"bin-win-vulkan-x64\.zip$", None)],
            "vulkan": [(r"bin-win-vulkan-x64\.zip$", None)],
        }.get(v, [])
        return orden + [(r"bin-win-(cpu-)?x64\.zip$", None)]
    orden = {"vulkan": [(r"bin-ubuntu-vulkan-x64\.(zip|tar\.gz)$", None)],
             "rocm": [(r"bin-ubuntu-rocm-[\d.]+-x64\.(zip|tar\.gz)$", None),
                      (r"bin-ubuntu-vulkan-x64\.(zip|tar\.gz)$", None)]}.get(v, [])
    return orden + [(r"bin-ubuntu-x64\.(zip|tar\.gz)$", None)]


async def _bajar(cliente: httpx.AsyncClient, url: str, destino: Path, etiqueta: str) -> None:
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    async with cliente.stream("GET", url, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        hecho, ultimo = 0, -1
        with open(tmp, "wb") as f:
            async for trozo in r.aiter_bytes(1 << 20):
                f.write(trozo)
                hecho += len(trozo)
                pct = int(hecho * 100 / total) if total else 0
                if pct != ultimo and pct % 2 == 0:
                    ultimo = pct
                    await hub.emitir("preparacion", activo=True, texto=f"Descargando {etiqueta}", progreso=pct)
    tmp.replace(destino)


def _extraer(archivo: Path, destino: Path) -> None:
    if archivo.name.endswith(".zip"):
        with zipfile.ZipFile(archivo) as z:
            z.extractall(destino)
    else:
        with tarfile.open(archivo) as t:
            t.extractall(destino, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(destino)
    archivo.unlink(missing_ok=True)


async def preparar_llama() -> Path:
    existente = binario_llama()
    if existente:
        return existente
    v = variante()
    motor = CONFIG["rutas"]["motor"] / v
    motor.mkdir(parents=True, exist_ok=True)
    await hub.emitir("preparacion", activo=True, texto=f"Buscando llama.cpp ({v})", progreso=0)
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=300)) as c:
        r = await c.get(GH_RELEASES, headers={"Accept": "application/vnd.github+json"})
        r.raise_for_status()
        elegido = None
        for rel in r.json():
            nombres = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
            for pat_bin, pat_extra in _patrones(v):
                binarios = [n for n in nombres if re.search(pat_bin, n)]
                extras = [n for n in nombres if pat_extra and re.search(pat_extra, n)]
                if binarios and (not pat_extra or extras):
                    elegido = [(n, nombres[n]) for n in binarios[:1] + extras[:1]]
                    break
            if elegido:
                log.info("llama.cpp %s: %s", rel.get("tag_name"), [n for n, _ in elegido])
                break
        if not elegido:
            raise RuntimeError("No encuentro una versión de llama.cpp para este sistema")
        for nombre, url in elegido:
            destino = motor / nombre
            await _bajar(c, url, destino, "llama.cpp")
            _extraer(destino, motor)
    b = binario_llama()
    if not b:
        raise RuntimeError("llama-server no aparece tras la descarga")
    if not es_windows():
        for f in b.parent.iterdir():
            if f.is_file():
                f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return b


async def preparar_voz() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=300)) as c:
        for clave, (url, nombre) in MODELOS_VOZ.items():
            if clave in ("segmentacion", "huella_voz") and not CONFIG["voz"].get("separar_voces", True):
                continue
            destino_final = carpeta_voz() / nombre
            if destino_final.exists():
                continue
            archivo = carpeta_voz() / url.rsplit("/", 1)[1]
            await _bajar(c, url, archivo, f"modelo de voz ({clave})")
            if archivo.name.endswith(".tar.bz2"):
                _extraer(archivo, carpeta_voz())


async def preparar_todo() -> None:
    try:
        await preparar_llama()
        await preparar_voz()
        await hub.emitir("preparacion", activo=False, texto="Listo", progreso=100)
    except Exception as e:  # la app sigue funcionando; se reintenta al reiniciar
        log.exception("Fallo preparando el motor")
        await hub.emitir("preparacion", activo=True, error=True,
                         texto=f"No pude descargar los componentes: {e}. Revisa la conexión y reinicia.",
                         progreso=0)


async def preparar_modelos() -> None:
    """Descarga por adelantado todos los modelos para poder trabajar sin conexión:
    cada perfil de llama.cpp (arrancándolo una vez) y el modelo de embeddings de Cognee."""
    from .memoria import _entorno
    from .motor import motor

    for perfil in motor.perfiles():
        log.info("Descargando modelo del perfil %s (la primera vez tarda)…", perfil)
        await motor.asegurar(perfil)
    await motor.cerrar()
    _entorno()
    from fastembed import TextEmbedding

    nombre = CONFIG["memoria"].get("embeddings", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    TextEmbedding(model_name=nombre, cache_dir=os.environ["FASTEMBED_CACHE_PATH"])
    log.info("Modelos listos en %s", CONFIG["rutas"]["modelos"])


def cache_llama() -> Path:
    p = CONFIG["rutas"]["modelos"] / "llama"
    p.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LLAMA_CACHE", str(p))
    return p
