# Cerebro local

Asistente 100 % local: el PC es el cerebro (llama.cpp, sherpa-onnx, Cognee) y el móvil es el kit de captura.
El grafo de conocimiento de Cognee flota como avatar en el centro de cada pantalla conectada.

## Manuales

- [Manual de usuario (PDF)](docs/Manual-de-usuario.pdf)
- [Manual técnico (PDF)](docs/Manual-tecnico.pdf)

Las fuentes de los manuales están en `docs/` (`manual-usuario.html`, `manual-tecnico.html`, `manual.css`, `img/`).

## Descargas

En [Releases](../../releases/latest): Windows portable (CUDA, ROCm, Vulkan, CPU), AppImage de Linux
(CUDA 12.9, ROCm, Vulkan, CPU y driver NVIDIA para el live de Ubuntu 24.04), APK de Android,
los dos manuales en PDF y el código fuente en zip.

## Código fuente

| Carpeta | Contenido |
|---|---|
| `cerebro/` | servidor (FastAPI + WebSocket), motor llama-server, voz, memoria Cognee, recetas, TUI |
| `web/` | interfaz web / PWA con el grafo 3D |
| `recetas/` | flujos editables en YAML |
| `android/` | app Android (WebView + grabación nativa + compartir) |
| `empaquetar/` | construcción de Windows portable y AppImage, scripts del driver NVIDIA |
| `docs/` | manuales |
| `.github/workflows/` | compilación de todos los binarios en GitHub Actions |

Probar sin modelos: `pip install -r requirements.txt && python -m cerebro simulado` → http://localhost:8765
