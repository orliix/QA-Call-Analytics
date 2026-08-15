import os
import tempfile
import streamlit as st
import google.generativeai as genai

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

st.title("🎙️ Call Analytics & Quality Assurance Agent")
st.caption("Plataforma de Auditoría Automática de Llamadas y Evaluación de Soft Skills")

with st.sidebar:
    st.header("⚙️ Configuración")
    api_key = st.text_input("Ingresa tu Gemini API Key:", type="password")
    st.info("🔒 Tus archivos de audio se analizan y se ELIMINAN automáticamente de los servidores al finalizar el proceso.")

if not api_key:
    st.warning("⚠️ Por favor, ingresa tu API Key en la barra lateral izquierda para comenzar.")
    st.stop()

# Configurar el SDK de Google
genai.configure(api_key=api_key)

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

# Configurar el modelo con temperatura 0.2
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash", # Puedes usar gemini-1.5-pro o gemini-2.5-flash
    system_instruction=SYSTEM_INSTRUCTIONS,
    generation_config={"temperature": 0.2}
)

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
            try:
                # 1. Subir audio a la API de Google Gemini
                google_audio_file = genai.upload_file(path=tmp_path)
                
                # 2. Generar el contenido usando el prompt configurado
                response = model.generate_content([google_audio_file, "Por favor procesa este audio siguiendo las System Instructions."])
                
                # 3. Mostrar el resultado
                st.success("✅ ¡Auditoría completada exitosamente!")
                
                # Mostrar resultado completo en markdown
                st.markdown(response.text)
                
                # Botón para descargar el reporte
                st.download_button(
                    label="📥 Descargar Reporte de QA (.txt)",
                    data=response.text,
                    file_name=f"Reporte_QA_{uploaded_file.name}.txt",
                    mime="text/plain"
                )

            except Exception as e:
                st.error(f"Ocurrió un error al procesar el audio: {str(e)}")

            finally:
                # 🛡️ SCRIPT DE DESTRUCCIÓN DE ARCHIVOS
                # Se ejecuta siempre, haya éxito o error
                if google_audio_file:
                    genai.delete_file(google_audio_file.name)
                    st.toast("🛡️ El archivo de audio fue eliminado permanentemente de los servidores de Google.", icon="🔒")
                
                # Eliminar archivo temporal local
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)