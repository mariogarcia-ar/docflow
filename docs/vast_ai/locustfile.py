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