# Catálogo de modelos locales menores a 10 GB

> **Criterio:** tamaño del **artefacto descargable** con cuantización Q4 (el default de Ollama/llama.cpp), salvo donde se indique otra cosa (`gpt-oss` va en MXFP4; los tags `-mlx` traen su propia cuantización). No es el tamaño de los pesos BF16.
> **Ojo:** para ejecutar, sumá 1–4 GB de KV cache según el contexto. Un modelo de 9 GB en disco necesita ~11–12 GB de VRAM/RAM.
> **Verificación:** cifras contrastadas con búsqueda web el **2026-09-30** contra Ollama Library y las model cards de Hugging Face. `n/d` = no verificado en esa pasada; `≈` = aproximado.

Leyenda: 👁️ visión · 🧠 razonamiento · 🔧 tool calling · 💻 código · 🌐 multilingüe · 🧩 MoE · 🔒 licencia no comercial

---

## 0. ¿Cuánto es un contexto? (para dimensionar)

**Las dos reglas de conversión:**

- **Texto:** tokens ≈ palabras × 1,33 (o caracteres ÷ 4). Una página A4 de prosa (500–750 palabras) son **650–1.000 tokens**. En español y en código el mismo texto cuesta ~20–40% más.
- **Imagen:** en los VLM de Qwen, **1 token visual = 28×28 píxeles** (parche ViT de 14×14 con fusión 2×2). Una página A4 escaneada a 150 dpi (1240×1754 px) ocupa ~2.835 tokens.

### 0.1 Contexto → páginas e imágenes

| Contexto | Páginas A4 de texto | Páginas A4 escaneadas @150 dpi | Imagen cuadrada que llenaría el contexto |
|---|---|---|---|
| 2K | 2–3 | no entra ni una | 1267×1267 px · 1,6 Mpx |
| 4K | 4–6 | 1 | 1792×1792 px · 3,2 Mpx |
| 8K | 8–12 | 2 | 2534×2534 px · 6,4 Mpx |
| 16K | 16–25 | 5 | 3584×3584 px · 12,9 Mpx |
| 32K | 32–49 | 11 | 5069×5069 px · 25,7 Mpx |
| 40K | 40–62 | 14 | 5667×5667 px · 32,1 Mpx |
| 64K | 64–98 | 23 | 7168×7168 px · 51,4 Mpx |
| 128K | 128–197 | 46 | 10137×10137 px · 102,8 Mpx |
| 200K | 200–308 | 72 | 12671×12671 px · 160,5 Mpx |
| 256K | 256–394 | 92 | 14336×14336 px · 205,5 Mpx |
| 1M | 1.000–1.538 | 352 | 28000×28000 px · 784 Mpx |

> **La columna de imágenes es un techo teórico, no un plan.** Por encima de ~16K tokens de imagen el límite lo pone el modelo, no el contexto: `max_pixels` de Qwen2.5-VL topa en 16.384 tokens por imagen (3584×3584, 12,8 Mpx) y Llama 3.2 Vision ni siquiera usa esta regla (topa en 1120×1120 px). El contexto sirve para **sumar varias páginas**, no para meter una foto gigante.

### 0.2 Cuánto pesa una imagen

| Entrada | Píxeles | Tokens visuales @28×28 | Para qué alcanza |
|---|---|---|---|
| Miniatura / logo | 384×384 | 196 | clasificar, no leer |
| Foto cuadrada | 1024×1024 | 1.369 | describir una imagen |
| Página A4 @150 dpi | 1240×1754 | 2.835 | leer texto impreso |
| Página A4 @200 dpi | 1654×2339 | 5.040 | el punto dulce para OCR |
| Página A4 @300 dpi | 2480×3508 | 11.214 | escaneo "de archivo" |
| Foto 12 Mpx | 4000×3000 | 15.444 | ya supera el tope por defecto |
| Tope por defecto de Qwen2.5-VL | 3584×3584 | 16.384 | `max_pixels` = 12,8 Mpx |

### 0.3 Lo que se olvida

- **Qwen3-VL cambió la aritmética:** usa **32×32 px por token**, no 28×28. La misma A4 a 150 dpi pasa de ~2.835 a ~2.145 tokens (y a 300 dpi, de ~11.214 a ~8.580). Copiar la config de Qwen2.5-VL y aplicarla a Qwen3-VL redimensiona las imágenes en silencio.
- **Llama 3.2 Vision cuenta distinto:** cross-attention, 1.601 tokens a 384×384 y 6.404 a 1080p, con tope de 1120×1120 px.
- **El contexto es entrada + salida.** Si pedís 2.000 tokens de respuesta, también ocupan ventana. Y el KV cache se come 1–4 GB extra de VRAM.
- **Una factura densa son ~2.000–5.000 tokens** (conceptos, totales, metadatos), no los ~700 de una página de novela.
- **1 hora de audio transcripto ≈ 9.000–16.000 tokens.**

---

## 1. Ultra-pequeños (< 2 GB) · edge, Raspberry Pi, CPU

| Modelo | Params | Tamaño (Q4) | Contexto | Licencia | Notas |
|---|---|---|---|---|---|
| Qwen3 | 0.6B | 523 MB | 40K | Apache 2.0 | 🧠 🔧 híbrido thinking |
| Qwen3 | 1.7B | 1.4 GB | 40K | Apache 2.0 | 🧠 🔧 |
| Qwen3.5 | 0.8B | 1.0 GB | 256K | Apache 2.0 | 👁️ visión nativa |
| Gemma 3 | 270M | 241 MB | 32K | Gemma Terms | ideal para fine-tuning y tareas simples |
| Gemma 3 | 1B | ~0.8 GB | 32K | Gemma Terms | 🌐 solo texto |
| Llama 3.2 | 1B | 1.3 GB | 128K | Llama 3.2 | |
| SmolLM2 | 135M / 360M / 1.7B | 271 MB / 726 MB / 1.8 GB | 8K | Apache 2.0 | muy livianos |
| TinyLlama | 1.1B | ~0.6 GB | 2K | Apache 2.0 | legacy, útil para pruebas |
| Qwen2.5-Coder | 1.5B | ~1.0 GB | 32K | Apache 2.0 | 💻 autocompletado |
| Qwen3-VL | 2B | 1.9 GB | 256K | Apache 2.0 | 👁️ OCR 32 idiomas |
| Moondream 2 | 1.9B | ~1.7 GB | n/d | Apache 2.0 | 👁️ |
| Granite 4 | 350M | 708 MB | 32K | Apache 2.0 | enterprise micro |

## 2. Pequeños (2–4 GB) · portátiles básicos, 8 GB RAM

| Modelo | Params | Tamaño (Q4) | Contexto | Licencia | Notas |
|---|---|---|---|---|---|
| Llama 3.2 | 3B | 2.0 GB | 128K | Llama 3.2 | 🔧 |
| Phi-4 Mini | 3.8B | 2.5 GB | 128K | MIT | 🧠 🔧 lógica y matemáticas, 24 idiomas |
| Qwen3 | 4B | 2.5 GB | 256K | Apache 2.0 | 🧠 🔧 🌐 |
| Qwen3.5 | 2B | 2.7 GB | 256K | Apache 2.0 | 👁️ |
| Qwen3.5 | 4B | 3.4 GB | 256K | Apache 2.0 | 👁️ 🧠 el mejor de su franja |
| Gemma 3 | 4B | 3.3 GB | 128K | Gemma Terms | 👁️ 🌐 muy sólido en español |
| Ministral 3 | 3B | 3.0 GB | 256K | Apache 2.0 | 👁️ 🔧 edge |
| Qwen3-VL | 4B | 3.3 GB | 256K | Apache 2.0 | 👁️ |
| Granite 4 | 3B (micro) | 2.1 GB | 128K | Apache 2.0 | 🔧 enterprise |
| Granite 4.1 | 3B | 2.1 GB | 128K | Apache 2.0 | 🔧 12 idiomas, JSON |
| Granite 4.2 | 3B | 2.2 GB | 128K | Apache 2.0 | 🧠 razonamiento nativo + tools |
| SmolLM3 | 3B | ~1.9 GB | 64K | Apache 2.0 | multilingüe, totalmente abierto |
| Phi-3.5 Mini | 3.8B | ~2.2 GB | 128K | MIT | |
| Gemma 2 | 2B | 1.6 GB | 8K | Gemma Terms | |
| Qwen2.5-VL | 3B | 3.2 GB | 125K | Apache 2.0 | 👁️ documentos y facturas |
| StarCoder2 | 3B | 1.7 GB | 16K | BigCode OpenRAIL-M | 💻 |
| CodeGemma | 2B | 1.6 GB | 8K | Gemma Terms | 💻 |

> **Corrección:** `Gemma 4 E2B/E4B` **no** entran acá: sus artefactos de Ollama pesan 7.2 GB y 9.6 GB (ver §4), más que el propio 12B. El nombre «edge» no refleja el peso del tag.

## 3. Gama media (4–7 GB) · 8 GB de VRAM

| Modelo | Params | Tamaño (Q4) | Contexto | Licencia | Notas |
|---|---|---|---|---|---|
| Llama 3.1 | 8B | 4.9 GB | 128K | Llama 3.1 | 🔧 buen generador para RAG |
| Qwen3 | 8B | 5.2 GB | 40K (128K nativo) | Apache 2.0 | 🧠 🔧 🌐 recomendado general |
| Qwen2.5 | 7B | 4.7 GB | 32K | Apache 2.0 | 🌐 |
| Qwen2.5-Coder | 7B | 4.7 GB | 32K | Apache 2.0 | 💻 |
| Mistral | 7B | 4.4 GB | 32K | Apache 2.0 | rápido, function calling |
| DeepSeek R1 (destilado Qwen) | 7B | 4.7 GB | 128K | MIT | 🧠 |
| DeepSeek R1 (destilado Llama) | 8B | 5.2 GB | 128K | MIT + Llama 3.1 | 🧠 |
| Gemma 2 | 9B | 5.4 GB | 8K | Gemma Terms | |
| Granite 3.3 | 8B | 4.9 GB | 128K | Apache 2.0 | 🔧 empresarial / RAG |
| Granite 4.1 | 8B | 5.3 GB | 128K | Apache 2.0 | 🔧 el más eficiente en tokens de su clase |
| Granite 4.2 | 8B | 5.3 GB | 128K | Apache 2.0 | 🧠 CoT nativo + tool calling |
| Aya Expanse | 8B | ~4.8 GB | 8K | 🔒 CC-BY-NC-4.0 | 🌐 23 idiomas, no comercial |
| Hermes 3 | 8B | ~4.9 GB | 128K | Llama 3.1 | 🔧 |
| Yi | 9B | ~5.0 GB | n/d | Apache 2.0 | |
| InternLM 2.5 | 7B | ~4.5 GB | n/d | Apache 2.0 | |
| OLMo 2 | 7B | 4.5 GB | 4K | Apache 2.0 | totalmente abierto (datos y receta) |
| Qwen3.5 | 9B | 6.6 GB | 256K | Apache 2.0 | 👁️ 🧠 mejor relación calidad/tamaño del catálogo |
| Qwen3-VL | 8B | 6.1 GB | 256K | Apache 2.0 | 👁️ 15–60% más rápido que Qwen2.5-VL 7B |
| Qwen2.5-VL | 7B | 6.0 GB | 125K | Apache 2.0 | 👁️ **muy bueno para facturas / JSON** |
| Ministral 3 | 8B | 6.0 GB | 256K | Apache 2.0 | 👁️ 🔧 |
| MiniCPM-V | 8B | 5.5 GB | 32K | Apache 2.0 | 👁️ OCR, 640 tokens por imagen |
| LLaVA 1.6 | 7B | 4.7 GB | 32K | Apache 2.0 | 👁️ |
| CodeGemma | 7B | 5.0 GB | 8K | Gemma Terms | 💻 |
| StarCoder2 | 7B | ~4.0 GB | 16K | BigCode OpenRAIL-M | 💻 |
| CodeLlama | 7B | 3.8 GB | 16K | Llama 2 | 💻 legacy |

> **Ojo con el contexto:** varias cifras de Ollama son deliberadamente cortas (`qwen3:8b` = 40K aunque el modelo soporta 128K; `nomic-embed-text` = 2K aunque soporta 8K). El contexto real se fija con `num_ctx` o `context_window`.

## 4. Gama media-alta (7–10 GB) · 12–16 GB de VRAM

| Modelo | Params | Tamaño (Q4) | Contexto | Licencia | Notas |
|---|---|---|---|---|---|
| Mistral Nemo | 12B | 7.1 GB | 128K | Apache 2.0 | 🔧 🌐 el tag de Ollama declara 1000K |
| Gemma 4 | 12B Unified | 7.6 GB | 256K | Apache 2.0 | 👁️ audio + imagen, encoder-free |
| Llama 3.2 Vision | 11B | 7.8 GB | 128K | Llama 3.2 | 👁️ solo inglés en imagen+texto |
| Gemma 3 | 12B | 8.1 GB | 128K | Gemma Terms | 👁️ 🌐 |
| Gemma 3 | 12B QAT | 8.9 GB | 128K | Gemma Terms | calidad cercana a BF16 |
| Gemma 4 | E2B / E4B | 7.2 / 9.6 GB | 128K | Apache 2.0 | 👁️ pesan más que el 12B: revisá el tag |
| DeepSeek Coder V2 Lite | 16B (🧩 ~2.4B activos) | 8.9 GB | 160K | DeepSeek | 💻 |
| DeepSeek R1 (destilado Qwen) | 14B | 9.0 GB | 128K | MIT | 🧠 |
| Qwen2.5 | 14B | 9.0 GB | 32K | Apache 2.0 | 🌐 |
| Qwen2.5-Coder | 14B | 9.0 GB | 32K | Apache 2.0 | 💻 |
| Phi-4 | 14B | 9.1 GB | 16K | MIT | 🧠 |
| StarCoder2 | 15B | 9.1 GB | 16K | BigCode OpenRAIL-M | 💻 |
| Ministral 3 | 14B | 9.1 GB | 256K | Apache 2.0 | 👁️ 🔧 |
| Qwen3 | 14B | 9.3 GB | 40K | Apache 2.0 | 🧠 🔧 🌐 |

> **Zona límite:** Phi-4, Qwen3 14B, StarCoder2 15B y Ministral 3 14B rondan los 9 GB. Con contexto largo no entran cómodos en una GPU de 12 GB.

---

## 5. Embeddings

| Modelo | Params | Tamaño | Contexto | Dims | Licencia | Notas |
|---|---|---|---|---|---|---|
| all-minilm | 23M | 46 MB | 256 | 384 | Apache 2.0 | mínimo, en inglés |
| nomic-embed-text v1.5 | 137M | 274 MB | 8K | 768 (MRL 64–768) | Apache 2.0 | el tag de Ollama declara 2K |
| EmbeddingGemma | 300M | 622 MB | 2K | 768 (MRL a 128) | Gemma Terms | rinde solo con prefijos |
| mxbai-embed-large | 335M | 670 MB | 512 | 1024 | Apache 2.0 | el mejor MTEB en tamaño BERT |
| bge-m3 | 567M | 1.2 GB | 8K | 1024 + disperso + multi-vector | MIT | denso + disperso, ideal para español |
| snowflake-arctic-embed2 | 568M | ~1.2 GB | 8K | 1024 (MRL a 256) | Apache 2.0 | rinde al nivel de un 8B en checo/eslávico |
| jina-embeddings-v3 | 570M | ~1.1 GB (FP16) | 8K | 1024 | 🔒 CC-BY-NC-4.0 | 🌐 no comercial |
| Qwen3-Embedding | 0.6B / 4B / 8B | 639 MB / 2.5 GB / 4.7 GB | 32K | 1024 / 2560 / 4096 (MRL 32+) | Apache 2.0 | MTEB multilingüe 70.58 (8B, #1 en junio 2025) |
| nomic-embed-text-v2-moe | MoE | n/d | n/d | n/d | Apache 2.0 | multilingüe MoE, tag nuevo |

## 6. Rerankers

| Modelo | Params | Tamaño | Contexto | Licencia | Notas |
|---|---|---|---|---|---|
| bge-reranker-v2-m3 | 568M | ~1.1 GB | 8K | Apache 2.0 | 🌐 cross-encoder clásico |
| Qwen3-Reranker | 0.6B / 4B / 8B | 639 MB / 2.5 GB / 4.7 GB | 32K | Apache 2.0 | 🌐 top de MTEB-R en su franja |
| Qwen3-VL-Reranker | 2B | n/d | 32K | Apache 2.0 | 👁️ multimodal (2026) |

## 7. OCR y documentos

| Modelo | Params | Tamaño | Salida | Licencia | Notas |
|---|---|---|---|---|---|
| Granite-Docling | 258M | 522 MB | DocTags | Apache 2.0 | PDF → formato estructurado, un solo pase |
| SmolDocling | 256M | ~0.5 GB | DocTags | Apache 2.0 | predecesor de Granite-Docling |
| Florence-2 | 230M / 770M | 0.5 / 1.5 GB | texto + cajas | MIT | OCR liviano con localización |
| PaddleOCR-VL | 0.9B | ~1.8 GB | Markdown | Apache 2.0 | 109 idiomas, tablas y fórmulas |
| Qwen3-VL | 2B / 4B / 8B | 1.9 / 3.3 / 6.1 GB | Markdown | Apache 2.0 | SOTA en OCR, 32 idiomas |
| Granite-Vision-3.3 | 2B | n/d | Markdown | Apache 2.0 | image-text, integrado en Docling |
| Qwen2.5-VL | 3B / 7B | 3.2 / 6.0 GB | Markdown | Apache 2.0 | facturas, tablas, JSON |
| olmOCR (2) | 7B | ~6 GB (cuantizado) | Markdown | Apache 2.0 | PDFs complejos, grounding visual |
| DeepSeek-OCR | 3B | ~6.7 GB (BF16) | Markdown | MIT | compresión contextual |

## 8. Audio y voz

| Modelo | Params | Tamaño | Función | Licencia | Notas |
|---|---|---|---|---|---|
| Whisper tiny → small | 39M / 74M / 244M | 0.08 / 0.15 / 0.5 GB | STT | MIT | multilingüe |
| Whisper large-v3-turbo | 809M | ~1.6 GB | STT | MIT | 4 capas de decoder, ~8× más rápido |
| Whisper large-v3 | 1.55B | ~3.1 GB (FP16) | STT | MIT | máxima calidad |
| Kokoro v1.0 | 82M | ~0.33 GB | TTS | Apache 2.0 | ~30× tiempo real, sin clonado |
| Piper | n/d (voces sueltas) | 0.06–0.1 GB por voz | TTS | MIT; fork GPL-3.0 | texto a voz en CPU |
| Orpheus | 3B / 1B / 400M / 150M | ~6 GB FP16 (3B) | TTS | Apache 2.0 | expresivo, clonado |
| Chatterbox | ~0.5B | ~1 GB | TTS | MIT | clonado de voz |

---

## 9. Recomendaciones rápidas (todas < 10 GB)

| Necesidad | Elección |
|---|---|
| Chat general | Qwen3.5 9B, Qwen3 8B, Llama 3.1 8B |
| Mejor calidad dentro del límite | Qwen3.5 9B, Gemma 4 12B, Qwen3 14B, Phi-4 (ojo: 16K de contexto) |
| Español | Gemma 3 12B / 4B, Qwen3.5, Granite 4.1 |
| Código | Qwen2.5-Coder 7B / 14B, Granite 4.1 8B |
| Razonamiento | DeepSeek R1 7B/14B, Phi-4 Mini, Qwen3/Qwen3.5 (modo thinking) |
| Tool calling / agentes | Qwen3.5 9B, Qwen3 8B, Granite 4.1 8B, Ministral 3 8B, Mistral Nemo |
| Facturas y extracción a JSON | Qwen3-VL 8B, Qwen2.5-VL 7B, Qwen3.5 9B, Gemma 3 12B |
| OCR de documentos escaneados | Granite-Docling, PaddleOCR-VL, olmOCR |
| Imagen + audio en un solo modelo | Gemma 4 12B Unified |
| RAG local | Llama 3.1 8B + bge-m3 + bge-reranker-v2-m3 |
| Licencia sin letra chica | Phi-4 (MIT), Qwen3.x (Apache 2.0), Granite (Apache 2.0) |
| Dispositivos edge | Phi-4 Mini, Llama 3.2 3B, Gemma 3 4B, Granite 4 350M |

> **Evitá para producción** los pesos marcados 🔒: Aya Expanse (CC-BY-NC-4.0) y jina-embeddings-v3 (CC-BY-NC-4.0) son solo para investigación y demos. Piper cambió de MIT a GPL-3.0 en el fork activo.

## 10. Quedan fuera (> 10 GB en Q4)

Referencia para saber dónde está el corte:

| Modelo | Tamaño (Q4) | Notas |
|---|---|---|
| Phi-4 reasoning 14B | ~11 GB | |
| gpt-oss 20B | 13 GB | 🧩 MXFP4, ~3.6B activos |
| Devstral 24B | 14 GB | 💻 46.8% SWE-Bench Verified |
| Mistral Small 3.2 24B | 15 GB | 👁️ 🔧 |
| Gemma 3 27B | 17 GB | 👁️ 128K |
| Qwen3.5 27B / Qwen3.6 27B | 17 GB | 👁️ 256K |
| Qwen3-Coder 30B | 18 GB | 💻 MoE, 3.3B activos |
| Gemma 4 26B MoE | 19 GB | 👁️ 256K, ~4B activos |
| Qwen3 30B-A3B | 19 GB | 🧩 256K |
| Gemma 4 31B dense | 20 GB | 👁️ 256K |
| Qwen2.5 / Qwen3 / R1 32B | 20 GB | |
| Command-R 35B | 20 GB | |
| Llama 3.3 70B / DeepSeek R1 70B | 43 GB | a 128K de contexto pasan los 100 GB |
| gpt-oss 120B | 65 GB | 🧩 entra en una GPU de 80 GB |
| Llama 4 Scout 109B | 65–67 GB | 🧩 |
| Mistral Medium 3.5 128B | 80 GB | |
| Qwen3.5 122B-A10B | 81 GB | 👁️ |
| Nemotron 3 Super 120B | 86 GB | 🧩 ~12B activos |
| Qwen3 235B-A22B | 142 GB | 🧩 |

## Notas

- **MoE en disco:** los modelos MoE pesan según el total de parámetros, no los activos. Por eso DeepSeek Coder V2 Lite (16B) pesa ~9 GB aunque corra rápido, y gpt-oss 20B (3.6B activos) pesa 13 GB.
- **MoE en velocidad:** los MoE sostienen su velocidad con contexto largo; los densos se derrumban. Un 35B-A3B hace ~60 tok/s donde un 128B denso hace 2.7.
- **KV cache:** es el costo real que no se ve en la tabla de descargas. Un 70B pasa de 43 GB a ~102 GB entre contexto de chat y 128K.
- **Cuantizaciones menores:** pasando a Q3 podés meter algunos modelos de ~20B en < 10 GB, a costa de calidad. No lo recomiendo para extracción estructurada.
- **Licencias:** el tamaño no dice nada sobre el uso comercial. Gemma (Gemma Terms), Llama (licencia comunitaria) y Aya Expanse (CC-BY-NC) tienen restricciones; Phi-4, Qwen y Granite son MIT/Apache 2.0.
- **Granite 4.2 (agosto 2026):** la generación 4.2 volvió a una arquitectura **densa** (abandonó el MoE híbrido Mamba-2 de 4.0) y sumó razonamiento nativo; son 3B (2.2 GB), 8B (5.3 GB) y 30B (18 GB), todos 128K y Apache 2.0. No confundir con `granite4` (350m/1b/3b, el MoE de 4.0).
- **Verificación:** el catálogo se contrastó el 2026-09-30 contra Ollama Library y las model cards. Las familias nuevas (Gemma 4, Qwen3.5/3.6, Ministral 3, Granite 4.1, Qwen3-VL) ya tienen cifras verificadas; quedan como `n/d` los tamaños que ninguna fuente publicada confirma.

## Fuentes consultadas (2026-09-30)

- Ollama Library: `qwen3`, `qwen3.5`, `qwen3-vl`, `qwen2.5`, `qwen2.5vl`, `qwen2.5-coder`, `deepseek-r1`, `deepseek-coder-v2`, `gemma2`, `gemma3`, `gemma4`, `llama3.2`, `llama3.2-vision`, `phi4`, `phi4-mini`, `mistral-nemo`, `ministral-3`, `granite3.3`, `granite4`, `granite4.1`, `smollm2`, `minicpm-v`, `llava`, `olmo2`, `codegemma`, `codellama`, `gpt-oss`, `ibm/granite-docling`.
- Model cards: `microsoft/Phi-4-mini-instruct`, `openai/whisper-large-v3-turbo`, `Qwen/Qwen3-Embedding-8B`, `Qwen/Qwen3-Reranker-8B`, `nomic-ai/nomic-embed-text-v1.5`, `BAAI/bge-m3`.
- Benchmarks y artículos: Artificial Analysis (Qwen3.5 small models, Granite 4.1), Modal (STT/TTS comparados), Docling Model Catalog, PaddleOCR-VL (arXiv 2510.14528), IBM Granite-Docling, roboflow (Florence-2 / Moondream 2).
- Aritmética de tokens visuales: model card de `Qwen/Qwen2-VL-7B-Instruct` (`min_pixels`/`max_pixels`),
  guía de fine-tuning de Qwen3-VL (32×32 px/token), arXiv 2504.00557 (tokens de imagen de Llama 3.2 Vision),
  `ai.meta.com` (Llama 3.2, contexto 128K) y las tablas de conversión página↔token.
