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
1. GENERATE A COMPLETE, VERBATIM TRANSCRIPT:
   - Identify distinct speakers.
   - Insert accurate timestamps at key intervals or speaker changes formatted as [MM:SS].
   - Capture every spoken word verbatim in the original language without summarizing, shortening, or paraphrasing the dialogue.

2. CALL OVERVIEW:
   - Reason for Call: 1-2 sentences summarizing the caller's main issue/request.
   - Resolution Provided: 1-2 sentences summarizing the outcome or next steps.

3. SOFT SKILLS & CUSTOMER SERVICE ASSESSMENT:
   - Tone & Professionalism: Evaluate customer handling, patience, and professional demeanor.
   - De-escalation & Empathy: Assess active listening, empathy, and control of the conversation.
   - Areas of Improvement: 1-2 bullet points or 'None' if handled exceptionally.

[REQUIRED TRANSCRIPTION OUTPUT SCHEMA]
#### Transcript
* **[00:00] Speaker 1:** [Full verbatim dialogue in original language]
*(Continue for the ENTIRE duration of the call)*

---

#### Call Overview
* **Reason for Call:** [Summary]
* **Resolution Provided:** [Outcome]

#### Soft Skills & Customer Service Assessment
* **Tone & Professionalism:** [Evaluation]
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
    "Selecciona un archivo de audio (.mp3, .wav, .m4a)", 
    type=["mp3", "wav", "m4a", "aac"]
)

if uploaded_file is not None:
    st.audio(uploaded_file, format="audio/mp3")

    if st.button("🚀 Procesar y Auditar Llamada", type="primary"):
        with st.spinner("Procesando llamada con Gemini AI... Esto puede tardar unos segundos según la duración."):

            # Guardar el archivo temporalmente en disco local
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{uploaded_file.name.split('.')[-1]}") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name

            google_audio_file = None
            max_intentos = 3

            try:
                # 1. Subir audio usando el cliente
                google_audio_file = client.files.upload(file=tmp_path)

                # 2. Generar el contenido, con reintentos automáticos si el servidor está ocupado
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
                            st.toast(f"⏳ Servidor ocupado, reintentando en {espera}s (intento {intento}/{max_intentos})...", icon="🔄")
                            time.sleep(espera)
                        else:
                            raise

                # 3. Guardar el reporte en la sesión (para que no se pierda al interactuar después)
                st.session_state["report"] = response.text

                # 4. Preparar una sesión de chat nueva, con la transcripción como contexto
                chat_system_instruction = f"""Eres un asistente que ayuda a un evaluador de calidad a discutir una llamada de servicio al cliente.
Ya existe una transcripción completa y una evaluación de soft skills de esta llamada, que se muestra a continuación.
Responde SIEMPRE basándote en esta información. Si te preguntan algo que no se puede saber a partir de la transcripción, dilo claramente.

=== TRANSCRIPCIÓN Y EVALUACIÓN DE LA LLAMADA ===
{response.text}
=== FIN DE LA TRANSCRIPCIÓN ===
"""
                st.session_state["chat_session"] = client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        system_instruction=chat_system_instruction,
                        temperature=0.3
                    )
                )
                st.session_state["chat_messages"] = []  # limpiar chat anterior si procesa una llamada nueva

            except Exception as e:
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
