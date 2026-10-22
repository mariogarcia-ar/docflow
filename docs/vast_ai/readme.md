Para hacer la prueba de estrés a Ollama usando Locust, usaremos el endpoint de compatibilidad con OpenAI (/v1/chat/completions) que especificas en tu comando curl, apuntando a tu URL de Cloudflare.
Sigue estos pasos para configurarlo y ejecutarlo:

1. Instalar Locust

Asegúrate de tener Python instalado y ejecuta en tu terminal:

```bash
pip install locust
```

Usa el código con precaución.

2. Crear el script de pruebas (locustfile.py)

Crea un archivo llamado locustfile.py en tu computadora y pega el siguiente código. Este script simulará usuarios enviando la petición exacta de tu ejemplo:

```python
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
