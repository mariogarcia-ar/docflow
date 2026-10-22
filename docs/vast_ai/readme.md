# notes
```bash

OLLAMA_HOST=0.0.0.0 ollama serve

```

# tutorial
To stress-test Ollama with Locust, use the OpenAI-compatible endpoint (`/v1/chat/completions`) through your Cloudflare URL. The script selects one text fixture from `tests/fixtures-txt/pdf_aptos_layout` for each request and asks the model to summarize it in Spanish. It assigns each request a unique ID and saves the response as `var/tools/locust/<request-key>.json`. Fixture contents are sent to the configured endpoint, so review them before running the test.
Sigue estos pasos para configurarlo y ejecutarlo:

1. Instalar Locust

Asegúrate de tener Python instalado y ejecuta en tu terminal:

```bash
pip install locust
```

Usa el código con precaución.

2. Crear el script de pruebas (locustfile.py)

Run the repository's `docs/vast_ai/locustfile.py` from the project root. It loads the fixture files relative to its own location:

```python
from pathlib import Path
import random

from locust import HttpUser, task, between

FIXTURES_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures-txt" / "pdf_aptos_layout"
)
DOCUMENTS = [
    (path.name, path.read_text(encoding="utf-8"))
    for path in sorted(FIXTURES_DIR.glob("*.txt"))
]
if not DOCUMENTS:
    raise FileNotFoundError(f"No text fixtures found in {FIXTURES_DIR}")

class OllamaStressTest(HttpUser):
    # Tiempo de espera aleatorio entre 1 y 3 segundos entre peticiones por usuario
    wait_time = between(1, 3) 

    @task
    def test_ollama_chat(self) -> None:
        filename, document = random.choice(DOCUMENTS)
        headers = {
            "Authorization": "Bearer 04e0485b9a3193cdad8f396e190bab9e2b18f7bac85d637bfce6f251653facbd",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "qwen3.5:9b",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Summarize the following document in Spanish. "
                        "Preserve its key information and do not invent details.\n\n"
                        f"File: {filename}\n\n{document}"
                    ),
                }
            ],
            "stream": False  # Se desactiva el streaming para medir el tiempo de respuesta completo
        }

        # Realiza la petición POST al endpoint de OpenAI compatible
        self.client.post("/v1/chat/completions", json=payload, headers=headers)
```
Usa
 el código con precaución.

3. Ejecutar Locust

En la misma carpeta donde guardaste el archivo, ejecuta el siguiente comando en tu terminal:

```bash
locust -f locustfile.py --host https://ranked-meetings-album-selection.trycloudflare.com
```

Usa el código con precaución.

4. Configurar la prueba en la interfaz web

1. Abre tu navegador web e ingresa a http://localhost:8089.
2. Verás un panel de configuración donde debes ingresar:
	• Number of users: La cantidad máxima de usuarios concurrentes simulados (ej. 10).
	• Ramp-up rate: Cuántos usuarios nuevos se añaden por segundo (ej. 1 para subir gradualmente).
3. Haz clic en "Start swarming".
A partir de ahí, verás gráficos en tiempo real con los tiempos de respuesta, la cantidad de peticiones por segundo (RPS) y si el servidor de Ollama empieza a fallar o a ponerse lento bajo carga masiva.
¿Quieres que modifiquemos el script para enviar prompts aleatorios o para medir el rendimiento usando streaming?
