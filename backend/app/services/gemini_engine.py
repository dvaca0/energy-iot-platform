import json
import os

from google import genai


def gemini_enabled():
    return os.getenv("LLM_ENABLED", "false").lower() == "true" and bool(os.getenv("GEMINI_API_KEY"))


def ask_gemini(question: str, context: dict) -> str:
    if not gemini_enabled():
        return ""

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    env_model = os.getenv("GEMINI_MODEL", "").strip()

    models = [
        env_model,
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
    ]

    models = [m for m in dict.fromkeys(models) if m]

    prompt = f"""
Eres el asistente de la plataforma Energy Intelligence para una tesis de monitoreo eléctrico IoT.

Responde en el mismo idioma del usuario.

Reglas:
- Usa los datos JSON como fuente principal.
- No inventes lecturas, edificios, costos, fechas, nodos ni anomalías.
- Sí puedes usar conocimiento técnico general para explicar conceptos eléctricos o de IA.
- Puedes explicar factor de potencia, corriente, voltaje, demanda, kWh, Random Forest, Isolation Forest y K-Means.
- Si faltan datos, dilo claramente.
- Sé técnico, claro y práctico.
- Usa Markdown limpio con títulos cortos, bullets y espacios.
- Responde máximo en 5 a 8 bullets salvo que el usuario pida más detalle.
- No escribas bloques largos de texto corrido.

Contexto del sistema:
{json.dumps(context, ensure_ascii=False, indent=2)}

Pregunta del usuario:
{question}
"""

    last_error = None

    for model in dict.fromkeys(models):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            text = (response.text or "").strip()
            if text:
                return text
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(f"Todos los modelos Gemini fallaron. Último error: {last_error}")
