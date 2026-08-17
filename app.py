import os
import re
import time
import base64
import tempfile
import datetime
import streamlit as st
import streamlit.components.v1 as components
import dropbox
from dropbox import DropboxOAuth2FlowNoRedirect
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

    with st.expander("🔗 Conectar Dropbox (solo la primera vez)"):
        st.caption("Usa esto una sola vez para obtener tu Refresh Token de Dropbox. Después lo guardas en tus Secrets de Streamlit y ya no necesitas volver a abrir esto.")

        dbx_app_key_temp = st.text_input("App Key de Dropbox", key="dbx_app_key_temp")
        dbx_app_secret_temp = st.text_input("App Secret de Dropbox", type="password", key="dbx_app_secret_temp")

        if dbx_app_key_temp and dbx_app_secret_temp:
            if st.button("1️⃣ Generar link de autorización"):
                st.session_state["dbx_oauth_flow"] = DropboxOAuth2FlowNoRedirect(
                    dbx_app_key_temp,
                    dbx_app_secret_temp,
                    token_access_type="offline"
                )
                st.session_state["dbx_auth_url"] = st.session_state["dbx_oauth_flow"].start()

            if "dbx_auth_url" in st.session_state:
                st.markdown(f"[👉 Haz clic aquí para autorizar Dropbox]({st.session_state['dbx_auth_url']})")
                st.caption("Inicia sesión, dale 'Allow', y Dropbox te va a mostrar un código. Cópialo y pégalo aquí abajo:")

                codigo_dbx = st.text_input("Código de autorización de Dropbox:", key="dbx_auth_code")

                if codigo_dbx and st.button("2️⃣ Obtener Refresh Token"):
                    try:
                        resultado_oauth = st.session_state["dbx_oauth_flow"].finish(codigo_dbx.strip())
                        st.success("¡Listo! Copia este Refresh Token y guárdalo en tus Secrets de Streamlit como DROPBOX_REFRESH_TOKEN:")
                        st.code(resultado_oauth.refresh_token)
                    except Exception as e:
                        st.error(f"No se pudo obtener el token: {str(e)}")

# La API Key ya no se escribe a mano: se lee de los secretos de Streamlit Cloud
api_key = st.secrets["GEMINI_API_KEY"]

# Configurar el cliente oficial UNA SOLA VEZ y guardarlo en la sesión.
if "client" not in st.session_state:
    st.session_state["client"] = genai.Client(
        api_key=api_key,
        http_options={'api_version': 'v1beta'}
    )

client = st.session_state["client"]

MODEL_NAME = 'gemini-3.1-flash-lite'


def sanitizar_para_nombre_archivo(texto):
    """Convierte texto libre en algo seguro para usar como nombre de archivo."""
    texto = re.sub(r'[^A-Za-z0-9_\-]+', '_', texto)
    texto = texto.strip('_')
    return texto if texto else "Agente"


SYSTEM_INSTRUCTIONS = """
[AGENT IDENTITY] You are a dedicated, verbatim Call Transcription Engine and Quality Specialist. Your persistent primary directive is to process provided call audio files into clean, accurate, an[...]
"""

# --- Espacio en memoria de la sesión: aquí se guarda el reporte y el chat ---
st.session_state.setdefault("report", None)
st.session_state.setdefault("agent_name", None)
st.session_state.setdefault("audit_date", None)
st.session_state.setdefault("processed_file_id", None)
st.session_state.setdefault("download_filename", "Reporte_QA.txt")
st.session_state.setdefault("download_content", "")
st.session_state.setdefault("chat_session", None)
st.session_state.setdefault("chat_messages", [])
st.session_state.setdefault("auto_download_done", False)
st.session_state.setdefault("dropbox_last_upload", None)

uploaded_file = st.file_uploader(
    "Selecciona un archivo de audio (.mp3, .wav, .m4a, .aac, .ogg, .flac, .aiff)",
    type=["mp3", "wav", "m4a", "aac", "ogg", "flac", "aiff", "aif"]
)

agent_name_input = st.text_input("Nombre del agente (respaldo, solo se usa si la IA no logra detectarlo en la llamada):", key="agent_name_input")

def generar_nombre_archivo(agent_name_sanitizado, descripcion="ReporteQA"):
    """Genera filename en formato YYYY-MM-DD_HHMMSS_Agente_Nombre_Descripción.txt"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{timestamp}_Agente_{agent_name_sanitizado}_{descripcion}.txt"

if uploaded_file is not None:
    st.audio(uploaded_file, format=uploaded_file.type)

    current_file_id = f"{uploaded_file.name}_{uploaded_file.size}"
    ya_procesado = st.session_state["processed_file_id"] == current_file_id

    if ya_procesado:
        st.info("✅ Esta llamada ya fue procesada. Si quieres auditarla de nuevo, sube el archivo otra vez o elige uno distinto.")

    if st.button("🚀 Procesar y Auditar Llamada", type="primary", disabled=ya_procesado):
        # reset auto-download flag for this new processing
        st.session_state["auto_download_done"] = False

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

            # Intentar extraer el nombre del agente que la IA detectó en la llamada.
            coincidencia_nombre = re.search(r"Agent Name.*?:\*\*\s*(.+)", response.text)
            nombre_detectado = coincidencia_nombre.group(1).strip() if coincidencia_nombre else ""
            nombre_no_valido = nombre_detectado.lower() in ["", "not stated", "n/a", "unknown", "none", "not mentioned", "no especificado"]

            if not nombre_no_valido:
                st.session_state["agent_name"] = nombre_detectado
            elif agent_name_input and agent_name_input.strip():
                st.session_state["agent_name"] = agent_name_input.strip()
            else:
                st.session_state["agent_name"] = "No especificado"

            st.session_state["audit_date"] = datetime.date.today().strftime("%d/%m/%Y")

            # 4. Preparar una sesión de chat nueva, usando un "cache" de contexto para no
            #    tener que reenviar (ni volver a cobrar) toda la transcripción en cada pregunta.
            chat_system_instruction = f"""Eres un asistente que ayuda a un evaluador de calidad a discutir una llamada de servicio al cliente.
Ya existe una transcripción completa y una evaluación de soft skills de esta llamada, que se muestra a continuación.
Responde SIEMPRE basándote en esta información. Si te preguntan algo que no se puede saber a partir de la transcripción, dilo claramente.
IMPORTANTE: Responde siempre en el mismo idioma en el que el usuario haga la pregunta (si pregunta en español, responde en español; si pregunta en inglés, responde en inglés), sin importar en qué idioma esté la transcripción o el resto de este reporte.

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
                st.session_state["chat_session"] = client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(
                        system_instruction=chat_system_instruction,
                        temperature=0.3
                    )
                )
            st.session_state["chat_messages"] = []  # limpiar chat anterior si procesa una llamada nueva
            st.session_state["processed_file_id"] = current_file_id

            # 5. Armar el nombre del archivo (Agente_Fecha_Hora_Descripción) y el contenido a descargar
            nombre_agente_archivo = sanitizar_para_nombre_archivo(st.session_state["agent_name"])
            # Generar filename con timestamp para evitar colisiones
            nombre_archivo = generar_nombre_archivo(nombre_agente_archivo, descripcion="ReporteQA")

            encabezado_txt = (
                f"Audited Agent: {st.session_state['agent_name']}\n"
                f"Audit Date: {st.session_state['audit_date']}\n\n"
            )

            # Evitar encabezado duplicado si la respuesta ya lo incluye
            if "Audited Agent:" in response.text and "Audit Date:" in response.text:
                contenido_descarga = response.text
            else:
                contenido_descarga = encabezado_txt + response.text

            st.session_state["download_filename"] = nombre_archivo
            st.session_state["download_content"] = contenido_descarga

            # 6. Descarga automática local: se dispara sola, pero sólo una vez por procesamiento
            b64_contenido = base64.b64encode(contenido_descarga.encode("utf-8")).decode()
            if not st.session_state.get("auto_download_done", False):
                components.html(
                    f"""
                    <html><body>
                    <a id="auto_download_link" href="data:text/plain;charset=utf-8;base64,{b64_contenido}" download="{nombre_archivo}"></a>
                    <script>
                        document.getElementById('auto_download_link').click();
                    </script>
                    </body></html>
                    """,
                    height=0,
                    width=0,
                )
                st.session_state["auto_download_done"] = True

            # 7. Subir automáticamente el reporte a Dropbox (si ya configuraste tus secrets de Dropbox)
            try:
                # Validar que los secrets de Dropbox existen
                dbx_app_key = st.secrets.get("DROPBOX_APP_KEY")
                dbx_app_secret = st.secrets.get("DROPBOX_APP_SECRET")
                dbx_refresh = st.secrets.get("DROPBOX_REFRESH_TOKEN")

                if not (dbx_app_key and dbx_app_secret and dbx_refresh):
                    raise KeyError("Faltan DROPBOX_APP_KEY / DROPBOX_APP_SECRET / DROPBOX_REFRESH_TOKEN en st.secrets")

                # Crear el cliente una sola vez por sesión
                if "dbx_client" not in st.session_state:
                    st.session_state["dbx_client"] = dropbox.Dropbox(
                        app_key=dbx_app_key,
                        app_secret=dbx_app_secret,
                        oauth2_refresh_token=dbx_refresh
                    )

                # Opcional: verificar la cuenta para depuración
                try:
                    acct = st.session_state["dbx_client"].users_get_current_account()
                    st.info(f"Dropbox conectado como: {acct.email}")
                except Exception as e:
                    st.warning(f"No se pudo verificar la cuenta de Dropbox: {e}")

                # Subir el fichero: use WriteMode.add para que Dropbox genere copias si ya existe
                metadata = st.session_state["dbx_client"].files_upload(
                    contenido_descarga.encode("utf-8"),
                    f"/{nombre_archivo}",
                    mode=dropbox.files.WriteMode.add,
                    autorename=True
                )

                # Guardar metadata útil en la sesión para localización posterior
                try:
                    server_mod = metadata.server_modified.isoformat() if hasattr(metadata, 'server_modified') else None
                except Exception:
                    server_mod = None

                st.session_state["dropbox_last_upload"] = {
                    "name": getattr(metadata, 'name', None),
                    "id": getattr(metadata, 'id', None),
                    "server_modified": server_mod,
                    "path_lower": getattr(metadata, 'path_lower', None)
                }

                st.toast(f"☁️ Reporte subido a tu Dropbox correctamente ({metadata.name}).", icon="✅")
                # Mostrar info adicional al usuario
                if st.session_state.get("dropbox_last_upload"):
                    info = st.session_state["dropbox_last_upload"]
                    st.info(f"Archivo en Dropbox: {info.get('name')} — subido: {info.get('server_modified')}")

            except KeyError as ke:
                # Dropbox no configurado en secrets; informar sin romper la app
                st.info(f"Dropbox no configurado en secrets: {ke}")
            except Exception as e:
                # Mostrar la excepción completa para depuración
                st.warning(f"No se pudo subir el reporte a Dropbox: {e}")

            progress_bar.progress(100, text="¡Listo!")
            time.sleep(0.5)
            progress_bar.empty()

        except Exception as e:
            # Except del try exterior (procesamiento completo)
            progress_bar.empty()
            st.error(f"Ocurrió un error al procesar el audio: {str(e)}")

        finally:
            # Cleanup: borrar el archivo subido a Gemini si existe y el tmp local
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
    st.success("✅ ¡Auditoría completada exitosamente! La descarga del reporte debió iniciar automáticamente.")

    encabezado_reporte = (
        f"**Audited Agent:** {st.session_state['agent_name']}  \n"
        f"**Audit Date:** {st.session_state['audit_date']}"
    )
    st.info(encabezado_reporte)
    st.markdown(st.session_state["report"])

    st.download_button(
        label="📥 Volver a descargar el Reporte de QA (.txt)",
        data=st.session_state["download_content"],
        file_name=st.session_state["download_filename"],
        mime="text/plain"
    )

    # Mostrar información de la última subida a Dropbox si existe
    if st.session_state.get("dropbox_last_upload"):
        info = st.session_state["dropbox_last_upload"]
        st.info(f"Última subida a Dropbox: {info.get('name')} — {info.get('server_modified')}")

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
