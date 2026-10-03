from ollama import chat

MODEL = 'qwen2.5:7b-instruct'


# 1. Definir la función/herramienta
def obtener_clima(ciudad: str) -> str:
    """Obtiene el clima actual de una ciudad."""
    # Simulación de respuesta de API
    return f"El clima en {ciudad} es de 22°C y soleado."


# Mapeo de nombre de función a objeto real
tools_map = {
    'obtener_clima': obtener_clima
}

# 2. Definir la especificación de la herramienta para el LLM
tools_definition = [
    {
        'type': 'function',
        'function': {
            'name': 'obtener_clima',
            'description': 'Obtiene el clima actual de una ciudad.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'ciudad': {
                        'type': 'string',
                        'description': 'Nombre de la ciudad',
                    },
                },
                'required': ['ciudad'],
            },
        },
    },
]

# 3. Llamada inicial al modelo
messages = [{'role': 'user', 'content': '¿Cómo está el clima en Buenos Aires?'}]
response = chat(
    model=MODEL,
    messages=messages,
    tools=tools_definition,
)

# 4. Manejar la llamada a la herramienta
if not response.message.tool_calls:
    print(response.message.content)
else:
    # El mensaje del asistente debe serializarse para volver al historial
    messages.append(response.message.model_dump())

    for tool in response.message.tool_calls:
        func_name = tool.function.name
        func_args = tool.function.arguments

        if func_name not in tools_map:
            continue

        # Ejecutar función local
        output = tools_map[func_name](**func_args)

        # Agregar respuesta de la herramienta al historial
        messages.append({
            'role': 'tool',
            'content': output,
            'tool_name': func_name,
        })

    # 5. Segunda llamada para que el modelo procese el resultado
    final_response = chat(model=MODEL, messages=messages)
    print(final_response.message.content)
