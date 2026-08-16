import os
import time
import tempfile
import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(
    page_title="Call Analytics & QA Transcriber",
    page_icon="🎙️",
    layout="wide"
)

st.markdown("""
    <style>
    .main { padding: 2rem; }
    .stAlert { margin-top: 1rem; }
    </style>
""", unsafe_allow_html=True)

# --- Pantalla de contraseña ---
def password_entered():
    if st.session_state["password_input"] == st.secrets["APP_PASSWORD"]:
        st.session_state["autenticado"] = True
        del st.session_state["password_input"]
    else:
        st.session_state["autenticado"] = False

def check_password():
    if st.session_state.get("autenticado", False):
        return True

    st.title("🔒 Acceso privado")
    st.text_input("Contraseña", type="password", on_change=password_entered, key="password_input")

    if "autenticado" in st.session_state and not st.session_state["autenticado"]:
        st.error("😕 Contraseña incorrecta, intenta de nuevo.")

    return False

if not check_password():
    st.stop()

st.title("🎙️ Call Analytics & Quality Assurance Agent")
st.caption("Plataforma de Auditoría Automática de Llamadas y Evaluación de Soft Skills")

with st.sidebar:
    st.header("⚙️ Configuración")
    st.info("🔒 Tus archivos de audio se analizan y se ELIMINAN automáticamente de los servidores al finalizar el proceso.")

# La API Key ya no se escribe a mano: se lee de los secretos de Streamlit Cloud
api_key = st.secrets["GEMINI_API_KEY"]

# Configurar el cliente oficial UNA SOLA VEZ y guardarlo en la sesión.
# (Si se crea uno nuevo en cada interacción, el chat se queda sin conexión y falla)
if "client" not in st.session_state:
    st.session_state["client"] = genai.Client(
        api_key=api_key,
        http_options={'api_version': 'v1beta'}
    )

client = st.session_state["client"]

MODEL_NAME = 'gemini-3.1-flash-lite'

SYSTEM_INSTRUCTIONS = """
[AGENT IDENTITY] You are a dedicated, verbatim Call Transcription Engine and Quality Specialist. Your persistent primary directive is to process provided call audio files into clean, accurate, and structured output.

[CORE WORKFLOW]
1. DETECT LANGUAGE AND GENERATE A COMPLETE, VERBATIM TRANSCRIPT:
   - Automatically detect the language(s) spoken in the call (e.g. Spanish, English, or a mix of both).
   - Transcribe each segment in the EXACT language it was spoken. Never translate — if the call switches languages mid-conversation (e.g. agent speaks English, customer replies in Spanish), preserve that switch faithfully.
   - Identify each distinct speaker and label them by their role based on context, not just "Speaker 1/2":
       * "Agente" — the company representative handling the call.
       * "Cliente" — the caller.
       * Any additional participant gets its own clear label (e.g. "Cliente 2", "Supervisor", "Intérprete") if more than two people speak.
   - Insert accurate timestamps at key intervals or speaker changes formatted as [MM:SS].
   - Capture every spoken word verbatim in the original language without summarizing, shortening, or paraphrasing the dialogue.
   - Flag any silence/dead air longer than 20 seconds directly inline in the transcript, e.g. "[Silencio - 25s]", at the point where it occurs.

2. CALL OVERVIEW:
   - Language(s) Detected: [e.g. "Español", "Inglés", or "Español e Inglés (mixto)"]
   - Reason for Call: 1-2 sentences summarizing the caller's main issue/request.
   - Resolution Provided: 1-2 sentences summarizing the outcome or next steps.

3. SOFT SKILLS & CUSTOMER SERVICE ASSESSMENT:
   Evaluate EACH item below individually. For each one, give a rating of "✅ Cumple", "⚠️ Parcial", "❌ No cumple", or "N/A" if it doesn't apply to this call, followed by a one-sentence justification (include a [MM:SS] timestamp reference when relevant):

   - **Profesionalismo durante toda la llamada:** ¿El agente mantuvo un trato profesional de principio a fin, sin excepciones?
   - **Evitó jerga técnica (jargon):** ¿El agente explicó las cosas en lenguaje claro y accesible para el cliente?
   - **Silencios muertos (dead air) mayores a 20 segundos:** Lista cada instancia detectada con su timestamp, o indica "Ninguno detectado".
   - **Tono de voz:** Clasifica como "Cálido y amigable", "Aceptable/estándar", o "Deficiente" — y si el tono se mantuvo consistente durante toda la llamada.
   - **Escucha activa:** ¿El agente mostró evidencia de escuchar activamente (parafraseo, confirmaciones, respuestas relevantes a lo dicho por el cliente)?
   - **Calidad de audio / ruido de fondo:** ¿Hubo ruido de fondo notable o problemas de calidad de audio que afectaran la comunicación?
   - **Expectativas de hold antes de una espera larga:** Si el agente puso al cliente en espera, ¿le explicó primero cuánto tiempo tomaría aproximadamente?
   - **Agradecimiento tras el hold:** Al regresar de la espera, ¿el agente agradeció al cliente por su paciencia/tiempo de espera?
   - **Protocolo de hold - check-in a los 3 minutos:** Si la espera superó los 3 minutos, ¿el agente regresó a la línea antes de ese punto para dar una actualización al cliente (aunque el asunto no estuviera resuelto aún)?
   - **De-escalation & Empathy:** Assess active listening, empathy, and control of the conversation during any tense moments.
   - **Areas of Improvement:** 1-2 bullet points, or "Ninguna" si el manejo fue excepcional en todos los puntos anteriores.

[REQUIRED TRANSCRIPTION OUTPUT SCHEMA]
#### Transcript
* **[00:00] Agente:** [Full verbatim dialogue in the language actually spoken]
* **[00:05] Cliente:** [Full verbatim dialogue in the language actually spoken]
*(Continue for the ENTIRE duration of the call, using the correct role label for each speaker)*

---

#### Call Overview
* **Idioma(s) detectado(s):** [Detected language(s)]
* **Reason for Call:** [Summary]
* **Resolution Provided:** [Outcome]

#### Soft Skills & Customer Service Assessment
* **Profesionalismo durante toda la llamada:** [Rating + justificación]
* **Evitó jerga técnica:** [Rating + justificación]
* **Silencios muertos (>20s):** [Lista de instancias o "Ninguno detectado"]
* **Tono de voz:** [Clasificación + consistencia]
* **Escucha activa:** [Rating + justificación]
* **Calidad de audio / ruido de fondo:** [Rating + justificación]
* **Expectativas de hold:** [Rating + justificación]
* **Agradecimiento tras el hold:** [Rating + justificación]
* **Check-in a los 3 minutos de hold:** [Rating + justificación]
* **De-escalation & Empathy:** [Evaluation]
* **Areas of Improvement:** [Bullet points]
"""

# --- Espacio en memoria de la sesión: aquí se guarda el reporte y el chat ---
if "report" not in st.session_state:
    st.session_state["report"] = None
if "chat_session" not in st.session_state:
    st.session_state["chat_session"] = None
if "chat_messages" not in st.session_state:
    st.session_state["chat_messages"] = []

uploaded_file = st.file_uploader(
    "Selecciona un archivo de audio (.mp3, .wav, .m4a, .aac, .ogg, .flac, .aiff)", 
    type=["mp3", "wav", "m4a", "aac", "ogg", "flac", "aiff", "aif"]
)

if uploaded_file is not None:
    st.audio(uploaded_file, format=uploaded_file.type)

    if st.button("🚀 Procesar y Auditar Llamada", type="primary"):
        progress_bar = st.progress(0, text="Preparando archivo...")

        # Guardar el archivo temporalmente en disco local
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name

        google_audio_file = None
        max_intentos = 3

        try:
            # 1. Subir audio usando el cliente
            progress_bar.progress(20, text="Subiendo audio a Gemini...")
            google_audio_file = client.files.upload(file=tmp_path)

            # 2. Generar el contenido, con reintentos automáticos si el servidor está ocupado
            progress_bar.progress(45, text="Analizando la llamada (transcripción y evaluación)...")
            response = None
            for intento in range(1, max_intentos + 1):
                try:
                    response = client.models.generate_content(
                        model=MODEL_NAME,
                        contents=[google_audio_file, "Por favor procesa este audio siguiendo las System Instructions."],
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTIONS,
                            temperature=0.2
                        )
                    )
                    break
                except Exception as err_intento:
                    if "503" in str(err_intento) and intento < max_intentos:
                        espera = 15 * intento
                        progress_bar.progress(45, text=f"⏳ Servidor ocupado, reintentando en {espera}s (intento {intento}/{max_intentos})...")
                        time.sleep(espera)
                    else:
                        raise

            progress_bar.progress(80, text="Preparando el reporte y el asistente de chat...")

            # 3. Guardar el reporte en la sesión (para que no se pierda al interactuar después)
            st.session_state["report"] = response.text

            # 4. Preparar una sesión de chat nueva, usando un "cache" de contexto para no
            #    tener que reenviar (ni volver a cobrar) toda la transcripción en cada pregunta.
            chat_system_instruction = f"""Eres un asistente que ayuda a un evaluador de calidad a discutir una llamada de servicio al cliente.
Ya existe una transcripción completa y una evaluación de soft skills de esta llamada, que se muestra a continuación.
Responde SIEMPRE basándote en esta información. Si te preguntan algo que no se puede saber a partir de la transcripción, dilo claramente.

=== TRANSCRIPCIÓN Y EVALUACIÓN DE LA LLAMADA ===
{response.text}
=== FIN DE LA TRANSCRIPCIÓN ===
"""
            try:
                # Guardamos la transcripción una sola vez en un cache (dura 1 hora)
                cache = client.caches.create(
                    model=MODEL_NAME,
                    config=types.CreateCachedContentConfig(
                        system_instruction=chat_system_instruction,
                        ttl="3600s",
                    )
                )
                st.session_state["chat_session"] = client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        cached_content=cache.name,
                        temperature=0.3
                    )
                )
            except Exception:
                # Si la llamada es muy corta, puede no alcanzar el mínimo de texto para cachear.
                # En ese caso, seguimos funcionando igual, solo que sin el ahorro del cache.
                st.session_state["chat_session"] = client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        system_instruction=chat_system_instruction,
                        temperature=0.3
                    )
                )
            st.session_state["chat_messages"] = []  # limpiar chat anterior si procesa una llamada nueva

            progress_bar.progress(100, text="¡Listo!")
            time.sleep(0.5)
            progress_bar.empty()

        except Exception as e:
            progress_bar.empty()
            st.error(f"Ocurrió un error al procesar el audio: {str(e)}")

        finally:
            if google_audio_file:
                try:
                    client.files.delete(name=google_audio_file.name)
                    st.toast("🛡️ El archivo de audio fue eliminado permanentemente de los servidores de Google.", icon="🔒")
                except Exception:
                    pass

            if os.path.exists(tmp_path):
                os.remove(tmp_path)

# --- Mostrar el reporte y el botón de descarga (persiste aunque interactúes con el chat) ---
if st.session_state["report"]:
    st.success("✅ ¡Auditoría completada exitosamente!")
    st.markdown(st.session_state["report"])

    st.download_button(
        label="📥 Descargar Reporte de QA (.txt)",
        data=st.session_state["report"],
        file_name="Reporte_QA.txt",
        mime="text/plain"
    )

    st.divider()
    st.subheader("💬 Discute los resultados con el asistente")
    st.caption("Pregúntale sobre el tono, la resolución, el cliente, o cualquier detalle de la llamada.")

    # Mostrar historial del chat
    for msg in st.session_state["chat_messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Caja de texto para preguntar
    pregunta = st.chat_input("Escribe tu pregunta sobre la llamada...")

    if pregunta:
        st.session_state["chat_messages"].append({"role": "user", "content": pregunta})
        with st.chat_message("user"):
            st.markdown(pregunta)

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                try:
                    respuesta_chat = st.session_state["chat_session"].send_message(pregunta)
                    st.markdown(respuesta_chat.text)
                    st.session_state["chat_messages"].append({"role": "assistant", "content": respuesta_chat.text})
                except Exception as e:
                    st.error(f"Ocurrió un error al responder: {str(e)}")
