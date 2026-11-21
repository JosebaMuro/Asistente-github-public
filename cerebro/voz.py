"""Voz con sherpa-onnx, todo en CPU.

- Decodifica cualquier audio (m4a, webm, ogg, mp3, wav) a 16 kHz mono con PyAV.
- Si hay modelos de separación de voces: diariza y transcribe cada turno.
- Si no: corta por silencios (VAD Silero) y transcribe cada trozo.
Transcripción con NeMo Parakeet TDT 0.6b v3 int8 (25 idiomas europeos, buen español).
"""
from __future__ import annotations

import gc
import logging
from pathlib import Path

import numpy as np

from . import descargas, simulado
from .config import CONFIG, SIMULADO

log = logging.getLogger("cerebro.voz")
SR = 16000
TROZO_MAX = 25.0  # segundos por trozo para el reconocedor

_reconocedor = None


def decodificar(ruta: Path) -> np.ndarray:
    import av

    partes = []
    with av.open(str(ruta)) as cont:
        flujo = next(s for s in cont.streams if s.type == "audio")
        remuestreo = av.audio.resampler.AudioResampler(format="flt", layout="mono", rate=SR)
        for paquete in cont.demux(flujo):
            for marco in paquete.decode():
                for m in remuestreo.resample(marco):
                    partes.append(m.to_ndarray().reshape(-1))
        for m in remuestreo.resample(None):
            partes.append(m.to_ndarray().reshape(-1))
    return np.concatenate(partes).astype(np.float32) if partes else np.zeros(0, np.float32)


def _hilos() -> int:
    return int(CONFIG["voz"].get("hilos", 4))


def _cargar_reconocedor():
    global _reconocedor
    if _reconocedor is None:
        import sherpa_onnx

        d = descargas.ruta_modelo_voz("asr")
        _reconocedor = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"),
            num_threads=_hilos(), model_type="nemo_transducer")
    return _reconocedor


def liberar() -> None:
    global _reconocedor
    _reconocedor = None
    gc.collect()


def _reconocer(muestras: np.ndarray) -> str:
    rec = _cargar_reconocedor()
    textos = []
    paso = int(TROZO_MAX * SR)
    for i in range(0, len(muestras), paso):
        st = rec.create_stream()
        st.accept_waveform(SR, muestras[i:i + paso])
        rec.decode_stream(st)
        textos.append(st.result.text.strip())
    return " ".join(t for t in textos if t)


def _por_silencios(muestras: np.ndarray) -> list[tuple[float, float]]:
    import sherpa_onnx

    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(descargas.ruta_modelo_voz("vad"))
    cfg.silero_vad.min_silence_duration = 0.4
    cfg.silero_vad.max_speech_duration = TROZO_MAX
    cfg.sample_rate = SR
    cfg.num_threads = 1
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
    ventana = cfg.silero_vad.window_size
    tramos = []

    def recoger():
        while not vad.empty():
            seg = vad.front
            tramos.append((seg.start / SR, (seg.start + len(seg.samples)) / SR))
            vad.pop()

    for i in range(0, len(muestras), ventana):
        vad.accept_waveform(muestras[i:i + ventana])
        recoger()
    vad.flush()
    recoger()
    return tramos


def _por_personas(muestras: np.ndarray) -> list[tuple[float, float, int]] | None:
    seg = descargas.ruta_modelo_voz("segmentacion") / "model.onnx"
    huella = descargas.ruta_modelo_voz("huella_voz")
    if not (CONFIG["voz"].get("separar_voces", True) and seg.exists() and huella.exists()):
        return None
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg)),
            num_threads=_hilos()),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(huella), num_threads=_hilos()),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=int(CONFIG["voz"].get("num_personas", -1)),
            threshold=float(CONFIG["voz"].get("umbral_voces", 0.5))),
        min_duration_on=0.3, min_duration_off=0.5)
    if not config.validate():
        log.warning("Configuración de separación de voces no válida; sigo sin ella")
        return None
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)
    resultado = sd.process(muestras).sort_by_start_time()
    turnos = []
    for r in resultado:  # une turnos seguidos de la misma persona
        if turnos and turnos[-1][2] == r.speaker and r.start - turnos[-1][1] < 1.0:
            turnos[-1] = (turnos[-1][0], r.end, r.speaker)
        else:
            turnos.append((r.start, r.end, r.speaker))
    return turnos


def _mmss(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def transcribir(ruta: Path, separar: bool = True) -> dict:
    """Devuelve {'segmentos': [...], 'texto': str, 'duracion': float, 'personas': int}."""
    if SIMULADO:
        return simulado.transcripcion(Path(ruta).name)
    muestras = decodificar(Path(ruta))
    duracion = len(muestras) / SR
    turnos = _por_personas(muestras) if separar else None
    segmentos = []
    if turnos:
        for ini, fin, persona in turnos:
            texto = _reconocer(muestras[int(ini * SR):int(fin * SR)])
            if texto:
                segmentos.append({"inicio": ini, "fin": fin, "persona": f"Persona {persona + 1}", "texto": texto})
    else:
        for ini, fin in _por_silencios(muestras) or [(0.0, duracion)]:
            texto = _reconocer(muestras[int(ini * SR):int(fin * SR)])
            if texto:
                segmentos.append({"inicio": ini, "fin": fin, "texto": texto})
    lineas = []
    for s in segmentos:
        quien = f"{s['persona']}: " if s.get("persona") else ""
        lineas.append(f"[{_mmss(s['inicio'])}] {quien}{s['texto']}")
    personas = len({s.get("persona") for s in segmentos if s.get("persona")})
    return {"segmentos": segmentos, "texto": "\n".join(lineas), "duracion": duracion, "personas": personas}


def transcribir_corto(ruta: Path) -> str:
    """Para preguntas por voz: sin separar personas ni marcas de tiempo."""
    if SIMULADO:
        return simulado.pregunta_por_voz()
    muestras = decodificar(Path(ruta))
    return _reconocer(muestras)
