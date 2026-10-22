necesito una serie de scripts para poder invocar ollama que se encuentra en una maquina de la red

```bash
curl http://192.168.1.104:11434/api/generate -d '{ "model": "llama3.2:3b", "prompt": "¿Por qué el cielo es azul?", "stream": false}'

```

