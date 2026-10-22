from locust import HttpUser, task, between

class OllamaStressTest(HttpUser):
    # Tiempo de espera aleatorio entre 1 y 3 segundos entre peticiones por usuario
    wait_time = between(1, 3) 

    @task
    def test_ollama_chat(self):
        headers = {
            "Authorization": "Bearer 04e0485b9a3193cdad8f396e190bab9e2b18f7bac85d637bfce6f251653facbd",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "qwen3.5:9b",
            "messages": [{"role": "user", "content": "Hello!"}],
            "stream": False  # Se desactiva el streaming para medir el tiempo de respuesta completo
        }

        # Realiza la petición POST al endpoint de OpenAI compatible
        self.client.post("/v1/chat/completions", json=payload, headers=headers)