# Catálogo de modelos locales menores a 10 GB

> **Criterio:** tamaño en disco con cuantización **Q4_K_M** (el default de Ollama/llama.cpp), salvo donde se indique otra cosa. Los tamaños son **aproximados**: verificalos en Ollama Library o Hugging Face antes de descargar.
> **Ojo:** para ejecutar, sumá 1–4 GB de KV cache según el contexto. Un modelo de 9 GB en disco necesita ~11–12 GB de VRAM/RAM.

Leyenda: 👁️ visión · 🧠 razonamiento · 🔧 tool calling · 💻 código · 🌐 multilingüe · 🧩 MoE

---

## 1. Ultra-pequeños (< 2 GB) · edge, Raspberry Pi, CPU

| Modelo | Params | Tamaño | Notas |
|---|---|---|---|
| Qwen3 | 0.6B | ~0.5 GB | 🧠 🔧 híbrido thinking |
| Qwen3 | 1.7B | ~1.4 GB | 🧠 🔧 |
| Gemma 3 | 270M | ~0.3 GB | Ideal para fine-tuning y tareas simples |
| Gemma 3 | 1B | ~0.8 GB | 🌐 solo texto |
| Llama 3.2 | 1B | ~1.3 GB | 128K contexto |
| SmolLM2 | 135M / 360M / 1.7B | 0.1 / 0.25 / 1.0 GB | Muy livianos |
| TinyLlama | 1.1B | ~0.6 GB | Legacy, útil para pruebas |
| Qwen2.5-Coder | 1.5B | ~1.0 GB | 💻 autocompletado |
| Moondream | 1.8B | ~1.7 GB | 👁️ |

## 2. Pequeños (2–4 GB) · portátiles básicos, 8 GB RAM

| Modelo | Params | Tamaño | Notas |
|---|---|---|---|
| Llama 3.2 | 3B | ~2.0 GB | 🔧 128K |
| Phi-4 Mini | 3.8B | ~2.5 GB | 🧠 🔧 lógica y matemáticas |
| Qwen3 | 4B | ~2.5 GB | 🧠 🔧 🌐 |
| Gemma 3 | 4B | ~3.3 GB | 👁️ 🌐 muy sólido en español |
| SmolLM3 | 3B | ~1.9 GB | Multilingüe, contexto largo |
| Ministral 3 | 3B | ~2 GB | 👁️ (tamaño sin verificar) |
| Phi-3.5 Mini | 3.8B | ~2.2 GB | |
| Gemma 2 | 2B | ~1.6 GB | |
| Qwen2.5-VL | 3B | ~3.2 GB | 👁️ documentos y facturas |
| StarCoder2 | 3B | ~1.7 GB | 💻 |
| CodeGemma | 2B | ~1.6 GB | 💻 |
| Gemma 4 | E2B / E4B | sin verificar | 👁️ audio, edge |
| Qwen 3.5 | 4B | sin verificar | 👁️ |

## 3. Gama media (4–7 GB) · 8 GB de VRAM

| Modelo | Params | Tamaño | Notas |
|---|---|---|---|
| Llama 3.1 | 8B | ~4.9 GB | 🔧 128K, buen generador para RAG |
| Qwen3 | 8B | ~5.2 GB | 🧠 🔧 🌐 recomendado general |
| Qwen2.5 | 7B | ~4.7 GB | 🌐 |
| Qwen2.5-Coder | 7B | ~4.7 GB | 💻 |
| Mistral | 7B | ~4.4 GB | Rápido, function calling |
| DeepSeek R1 (destilado Qwen) | 7B | ~4.7 GB | 🧠 |
| DeepSeek R1 (destilado Llama) | 8B | ~5.2 GB | 🧠 |
| Gemma 2 | 9B | ~5.4 GB | |
| Granite 3.3 | 8B | ~4.9 GB | 🔧 empresarial / RAG |
| Aya Expanse | 8B | ~4.8 GB | 🌐 |
| Hermes 3 | 8B | ~4.9 GB | 🔧 |
| Yi | 9B | ~5.0 GB | |
| InternLM 2.5 | 7B | ~4.5 GB | |
| OLMo 2 | 7B | ~4.5 GB | Totalmente abierto |
| Qwen2.5-VL | 7B | ~6.0 GB | 👁️ **muy bueno para facturas / JSON** |
| MiniCPM-V | 8B | ~5.5 GB | 👁️ OCR |
| LLaVA | 7B | ~4.7 GB | 👁️ |
| Ministral 3 | 8B | ~5 GB | 👁️ 🔧 (sin verificar) |
| CodeGemma | 7B | ~5.0 GB | 💻 |
| StarCoder2 | 7B | ~4.0 GB | 💻 |
| CodeLlama | 7B | ~3.8 GB | 💻 legacy |
| Qwen 3.5 | 9B | sin verificar | 👁️ |

## 4. Gama media-alta (7–10 GB) · 12–16 GB de VRAM

| Modelo | Params | Tamaño | Notas |
|---|---|---|---|
| Llama 3.2 Vision | 11B | ~7.8 GB | 👁️ |
| Mistral Nemo | 12B | ~7.1 GB | 🔧 🌐 128K |
| Gemma 3 | 12B | ~8.1 GB | 👁️ 🌐 |
| DeepSeek Coder V2 Lite | 16B (🧩 ~2.4B activos) | ~8.9 GB | 💻 |
| DeepSeek R1 (destilado Qwen) | 14B | ~9.0 GB | 🧠 |
| Qwen2.5 | 14B | ~9.0 GB | 🌐 |
| Qwen2.5-Coder | 14B | ~9.0 GB | 💻 |
| Phi-4 | 14B | ~9.1 GB | 🧠 |
| Qwen3 | 14B | ~9.3 GB | 🧠 🔧 🌐 |
| StarCoder2 | 15B | ~9.1 GB | 💻 |
| Gemma 4 | 12B Unified | sin verificar | 👁️ |

> **Zona límite:** Phi-4, Qwen3 14B y StarCoder2 15B rondan los 9 GB. Con contexto largo no entran cómodos en una GPU de 12 GB.

---

## 5. Embeddings

| Modelo | Params | Tamaño | Notas |
|---|---|---|---|
| all-minilm | 23M | ~0.05 GB | Mínimo, en inglés |
| nomic-embed-text | 137M | ~0.27 GB | Contexto 8K |
| EmbeddingGemma | 308M | ~0.6 GB | 🌐 |
| mxbai-embed-large | 335M | ~0.67 GB | |
| Qwen3-Embedding | 0.6B / 4B / 8B | 0.6 / 2.5 / 4.7 GB | 🌐 muy buen rendimiento |
| bge-m3 | 567M | ~1.2 GB | 🌐 denso + disperso, ideal para español |
| snowflake-arctic-embed | 22M–335M | 0.05–0.7 GB | |
| jina-embeddings-v3 | 570M | ~1.1 GB (FP16) | 🌐 |

## 6. Rerankers

| Modelo | Tamaño | Notas |
|---|---|---|
| bge-reranker-v2-m3 | ~1.1 GB | 🌐 |
| Qwen3-Reranker 0.6B / 4B / 8B | 0.6 / 2.5 / 4.7 GB | 🌐 |

## 7. OCR y documentos

| Modelo | Params | Tamaño | Notas |
|---|---|---|---|
| Granite-Docling | 258M | ~0.5 GB | PDF → formato estructurado |
| Florence-2 | 230M / 770M | 0.5 / 1.5 GB | OCR liviano |
| PaddleOCR-VL | 0.9B | ~1.8 GB | Tablas y fórmulas |
| Qwen2.5-VL | 3B / 7B | 3.2 / 6.0 GB | Facturas, tablas, JSON |
| olmOCR | 7B | ~6 GB (cuantizado) | PDFs complejos |
| DeepSeek-OCR | 3B | ~6.7 GB (BF16) | |

## 8. Audio y voz

| Modelo | Tamaño | Función |
|---|---|---|
| Whisper tiny → small | 0.08–0.5 GB | Transcripción |
| Whisper large-v3-turbo | ~1.6 GB | Transcripción rápida |
| Whisper large-v3 | ~3.1 GB (FP16) | Máxima calidad |
| Kokoro | ~0.33 GB | Texto a voz |
| Piper | 0.06–0.1 GB | Texto a voz en CPU |
| Orpheus 3B | ~2–6 GB según cuantización | Texto a voz expresivo |

---

## 9. Recomendaciones rápidas (todas < 10 GB)

| Necesidad | Elección |
|---|---|
| Chat general | Qwen3 8B, Llama 3.1 8B |
| Mejor calidad dentro del límite | Qwen3 14B, Phi-4 (si entra) |
| Español | Gemma 3 12B / 4B, Qwen3 |
| Código | Qwen2.5-Coder 7B / 14B |
| Razonamiento | DeepSeek R1 7B/14B, Phi-4 Mini, Qwen3 (modo thinking) |
| Tool calling / agentes | Qwen3 8B, Llama 3.1 8B, Granite 3.3 8B, Mistral Nemo |
| Facturas y extracción a JSON | Qwen2.5-VL 7B, Gemma 3 12B |
| RAG local | Llama 3.1 8B + bge-m3 + bge-reranker-v2-m3 |
| Dispositivos edge | Phi-4 Mini, Llama 3.2 3B, Gemma 3 4B |

## 10. Quedan fuera (> 10 GB en Q4)

Referencia para saber dónde está el corte:

| Modelo | Tamaño aprox. |
|---|---|
| gpt-oss 20B | ~13 GB |
| Phi-4 reasoning 14B | ~11 GB |
| Mistral Small / Devstral 24B | ~14 GB |
| Qwen3 30B-A3B / Qwen3-Coder 30B | ~18 GB |
| Gemma 3 27B | ~17 GB |
| Qwen2.5 / Qwen3 / R1 32B | ~19–20 GB |
| Command-R 35B | ~20 GB |
| Llama 3.3 70B | ~43 GB |
| gpt-oss 120B | ~65 GB |
| Llama 4 Scout 109B | ~65 GB |

## Notas

- **MoE en disco:** los modelos MoE pesan según el total de parámetros, no los activos. Por eso DeepSeek Coder V2 Lite (16B) pesa ~9 GB aunque corra rápido.
- **Cuantizaciones menores:** pasando a Q3 podés meter algunos modelos de ~20B en < 10 GB, a costa de calidad. No lo recomiendo para extracción estructurada.
- **Gemma 4 y Qwen 3.5/3.6:** vienen de tu documento original y no pude verificar sus tamaños.
