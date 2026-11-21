# Cerebro local

Asistente 100 % local: el PC es el cerebro (llama.cpp, sherpa-onnx, Cognee) y el móvil es el kit de captura.
El grafo de conocimiento de Cognee flota como avatar en el centro de cada pantalla conectada.

- `cerebro/` servidor (FastAPI) · `web/` interfaz · `recetas/` flujos editables · `android/` app
- `empaquetar/` construcción de Windows portable y AppImage de Linux (CUDA 12.9 + Vulkan + CPU, driver NVIDIA para live de Ubuntu 24.04)
- `docs/` manual de usuario y manual técnico (PDF)

Probar sin modelos: `pip install -r requirements.txt && python -m cerebro simulado` → http://localhost:8765

Binarios: pestaña **Actions → Compilar**, o **Releases** al subir una etiqueta `v*`.
