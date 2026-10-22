import json
from pathlib import Path
import random
from uuid import uuid4

from locust import HttpUser, task, between

FIXTURES_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures-txt" / "pdf_aptos_layout"
)
OUTPUT_DIR = Path(__file__).resolve().parents[2] / "var" / "tools" / "locust"
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
        request_key = uuid4().hex
        filename, document = random.choice(DOCUMENTS)
        headers = {
            "Authorization": "Bearer 04e0485b9a3193cdad8f396e190bab9e2b18f7bac85d637bfce6f251653facbd",
            "Content-Type": "application/json"
        }
        headers["X-Request-ID"] = request_key

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

        response = self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers=headers,
            name="/v1/chat/completions",
        )
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"{request_key}.json"
        output_path.write_text(
            json.dumps(
                {
                    "request_key": request_key,
                    "fixture": filename,
                    "status_code": response.status_code,
                    "response": response.text,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )