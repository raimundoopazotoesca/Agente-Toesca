import json
import base64
import streamlit as st
from pathlib import Path

# Avatar del agente: "t." en estilo marca Toesca
_AGENT_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 36 36" width="36" height="36">
  <rect width="36" height="36" rx="4" fill="#111111" stroke="#222222" stroke-width="1"/>
  <text x="18" y="25" text-anchor="middle"
        font-family="Georgia,'Times New Roman',serif"
        font-size="17" font-weight="400" letter-spacing="-0.5"
        fill="#e8e3dc">t.</text>
</svg>"""
_AGENT_AVATAR = "data:image/svg+xml;base64," + base64.b64encode(_AGENT_SVG).decode()

from agent import (
    client, MODEL, BASE_PROMPT, PROMPT_CDG, PROMPT_NOI, PROMPT_RENTROLL, PROMPT_CAJA,
    _select_tools, _dispatch, _llm_call, get_intent_groups,
    _MAX_TOOL_ITERS,
)

_MAX_HISTORY_TURNS = 3   # pares usuario/agente a mantener en contexto
from tools.memory_tools import load_memory, guardar_tarea

# ─── Página ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente Toesca",
    page_icon="favicon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Pantalla de carga (Garantizada sin interrupciones) ────────────────────────
import time

if st.session_state.get("authentication_status") is True:
    if "loader_start_time" not in st.session_state:
        st.session_state.loader_start_time = time.time()

    if time.time() - st.session_state.loader_start_time < 3.5:
        # Prevenimos el flash de la UI nativa ocultándola brevemente 
        # mientras el iframe inyecta el loader en el DOM
        st.markdown("""
        <style>
        @keyframes toesca-prevent-flash {
            0% { opacity: 0; }
            100% { opacity: 1; }
        }
        [data-testid="stAppViewContainer"],
        [data-testid="stSidebar"],
        header[data-testid="stHeader"] {
            animation: toesca-prevent-flash 0.1s ease-in 0.8s both !important;
        }
        </style>
        """, unsafe_allow_html=True)

        # Inyectamos el loader directamente en el DOM raíz (fuera de React)
        # Esto evita que Streamlit destruya o reinicie la animación durante los reruns
        st.iframe("""
        <script>
        (function() {
            var parentDoc = window.parent.document;
            
            // Si ya está inyectado, no hacemos nada (mantiene la animación fluida)
            if (parentDoc.getElementById('toesca-loader-container')) return;
            
            var container = parentDoc.createElement('div');
            container.id = 'toesca-loader-container';
            container.innerHTML = `
                <style>
                @import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400&display=swap');

                #toesca-loader {
                  position: fixed;
                  inset: 0;
                  background: #0a0a0a;
                  z-index: 9999999;
                  display: flex;
                  align-items: center;
                  justify-content: center;
                  flex-direction: column;
                  animation: tl-fadeout 0.6s cubic-bezier(0.4,0,1,1) 2.9s forwards;
                }
                .tl-content { display: flex; align-items: center; justify-content: center; }
                .tl-logo {
                  font-family: 'EB Garamond', Georgia, serif; font-size: 5rem;
                  font-weight: 400; color: #e8e3dc; display: flex; align-items: baseline;
                  line-height: 1; overflow: visible; position: relative;
                }
                .tl-text { opacity: 0; animation: tl-textin 0.8s ease-out 0.2s forwards; }
                .tl-dot {
                  display: inline-block; opacity: 0; transform: translateX(-48vw);
                  animation: tl-dotin 1.0s cubic-bezier(0.34,1.45,0.64,1) 1.2s forwards;
                  color: #e8e3dc;
                }
                .tl-bar { position: fixed; bottom: 0; left: 0; width: 100%; height: 1px; background: #1a1a1a; }
                .tl-progress {
                  height: 100%;
                  background: linear-gradient(90deg, transparent, #e8e3dc 15%, #e8e3dc 85%, transparent);
                  width: 0;
                  animation: tl-progress 3.5s linear 0s forwards;
                }

                @keyframes tl-textin {
                  0%   { opacity: 0; transform: translateY(10px); }
                  100% { opacity: 1; transform: translateY(0);    }
                }
                @keyframes tl-dotin {
                  0%   { opacity: 0; transform: translateX(-48vw); }
                  12%  { opacity: 1;                               }
                  100% { opacity: 1; transform: translateX(0);     }
                }
                @keyframes tl-progress {
                  from { width: 0%;    }
                  to   { width: 100%;  }
                }
                @keyframes tl-fadeout {
                  from { opacity: 1; }
                  to   { opacity: 0; pointer-events: none; }
                }
                </style>
                <div id="toesca-loader">
                  <div class="tl-content">
                    <div class="tl-logo"><span class="tl-text">toesca</span><span class="tl-dot">.</span></div>
                  </div>
                  <div class="tl-bar"><div class="tl-progress"></div></div>
                </div>
            `;
            parentDoc.body.appendChild(container);
            
            // Eliminar del DOM una vez terminada la animación
            setTimeout(function() {
                if (container.parentNode) container.parentNode.removeChild(container);
            }, 3500);
        })();
        </script>
        """, width="content", height="content")

# ─── Autenticación y Pantalla de Login Elegante ──────────────────────────────
import yaml
from yaml.loader import SafeLoader
import streamlit_authenticator as stauth

with open('config.yaml', encoding='utf-8') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

# Si el usuario no está logueado (status is None o False), mostramos la pantalla custom y paramos
if st.session_state.get("authentication_status") is not True:

    if "loader_start_time" in st.session_state:
        del st.session_state["loader_start_time"]

    _err_msg = "Usuario o contraseña incorrectos" if st.session_state.get("authentication_status") is False else ""

    # CSS global: ocultar chrome de Streamlit + esconder form nativo fuera de pantalla
    st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
    [data-testid="collapsedControl"],
    [data-testid="stSidebar"],
    header[data-testid="stHeader"] { display: none !important; }
    [data-testid="stAppViewContainer"], .main { background: #050505 !important; }
    .block-container { padding-top: 0 !important; padding-bottom: 0 !important; }
    div[data-testid="stForm"] {
        position: fixed !important; left: -9999px !important;
        top: 0 !important; width: 1px !important; height: 1px !important;
        overflow: hidden !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Form nativo: fuera de pantalla, funcional (maneja auth + cookies)
    try:
        authenticator.login('main')
    except Exception:
        pass

    # UI personalizada: iframe completo, sin interferencia del parser de Markdown
    _html = open('login_template.html', encoding='utf-8').read().replace('__ERR__', _err_msg)
    st.iframe(_html, height=720)

    if st.session_state.get("authentication_status") is True:
        st.rerun()
    else:
        st.stop()


else:
    # IMPORTANTE: Llamar a login silenciosamente cuando ya está autenticado
    # para que Streamlit-Authenticator escriba y mantenga las cookies de sesión.
    authenticator.login('main')

# ─── Inyectar CSS desde archivo externo ───────────────────────────────────────
css = Path("style.css").read_text(encoding="utf-8")
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

# ─── Botón sidebar ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
#toesca-sidebar-btn {
    position: fixed; top: 12px; left: 12px; z-index: 99999;
    width: 30px; height: 30px;
    background: #141414; border: 1px solid #252525; border-radius: 5px;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; color: #666; font-size: 13px; line-height: 1;
    transition: color .15s, border-color .15s; user-select: none;
}
#toesca-sidebar-btn:hover { color: #e8e3dc; border-color: #555; }
</style>
<div id="toesca-sidebar-btn" title="Sidebar">&#9776;</div>
""", unsafe_allow_html=True)

st.iframe("""
<script>
(function() {
    var parentDoc = window.parent.document;
    
    function toggleSidebar() {
        var ids = ['stSidebarCollapsedControl', 'stSidebarCollapseButton', 'collapsedControl', 'baseButton-headerNoPadding'];
        for (var i=0; i<ids.length; i++) {
            var el = parentDoc.querySelector('[data-testid="'+ids[i]+'"]');
            if (el) {
                var b = el.tagName === 'BUTTON' ? el : el.querySelector('button');
                if (b) { b.click(); return; }
                el.click(); return;
            }
        }
        var buttons = parentDoc.querySelectorAll('button');
        for (var j=0; j<buttons.length; j++) {
            var aria = (buttons[j].getAttribute('aria-label') || '').toLowerCase();
            var testid = (buttons[j].getAttribute('data-testid') || '').toLowerCase();
            if (aria.includes('sidebar') || testid.includes('sidebar')) {
                buttons[j].click();
                return;
            }
        }
        var header = parentDoc.querySelector('header');
        if (header) {
            var btn = header.querySelector('button');
            if (btn) { btn.click(); return; }
        }
    }

    function attachListener() {
        var btn = parentDoc.getElementById('toesca-sidebar-btn');
        if (btn && !btn.hasAttribute('data-listener')) {
            btn.setAttribute('data-listener', 'true');
            btn.addEventListener('click', toggleSidebar);
        }
    }
    
    // Attempt attachment immediately and also observe mutations in case it re-renders
    attachListener();
    var observer = new MutationObserver(attachListener);
    observer.observe(parentDoc.body, { childList: true, subtree: true });
})();
</script>
""", width="content", height="content")



# ─── Estado ────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="toesca-logo">toesca.</p>', unsafe_allow_html=True)
    st.markdown('<p class="toesca-tagline">Gestión de Fondos</p>', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:13px; color:#888; padding-bottom:10px;">👤 {st.session_state.get("name", "")}</div>', unsafe_allow_html=True)
    authenticator.logout('Cerrar Sesión', 'main')
    
    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    st.markdown('<p class="sidebar-section">Acciones rápidas</p>', unsafe_allow_html=True)
    for icon, label in [
        ("📊", "Crear planilla del mes"),
        ("💰", "Actualizar NOI completo"),
        ("🏦", "Copiar saldo caja al CDG"),
        ("📋", "Revisar rent rolls"),
        ("📈", "Obtener precios bursátiles"),
    ]:
        if st.button(f"{icon}  {label}", key=f"qa_{label}"):
            st.session_state.pending_input = label
            st.rerun()

    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Fondos</p>', unsafe_allow_html=True)
    for f in ["Toesca Rentas Inmobiliarias", "Toesca Rentas Inmobiliarias PT", "Toesca Rentas Inmobiliarias Apoquindo"]:
        st.markdown(f'<div style="font-family:Inter,sans-serif;font-size:0.78rem;color:#555;padding:0.3rem 0">{f}</div>', unsafe_allow_html=True)

    if st.session_state.messages:
        st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)
        if st.button("🗑  Nueva conversación", key="clear"):
            st.session_state.messages = []
            st.rerun()

# ─── Procesar input inicial ──────────────────────────────────────────────────
_pending = st.session_state.get("pending_input")
if _pending:
    st.session_state.pending_input = None

user_input = st.chat_input("Escribe una instrucción...") or _pending

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})

# ─── Área principal (Renderizar historial o Welcome) ─────────────────────────
# ─── Área principal (Renderizar historial o Welcome) ─────────────────────────
# 1. Componente estático: SIEMPRE debe ser el primer elemento para que Streamlit
# no lo destruya al re-renderizar, permitiendo la transición CSS fluida.
st.markdown("""
<div class="welcome-container" id="toesca-welcome-ui">
    <div class="welcome-logo">toesca.</div>
    <div class="welcome-fade-group">
        <div class="welcome-tagline">Agente de Gestión de Fondos</div>
        <div class="welcome-desc">
            Puedo actualizar el Control de Gestión, calcular el NOI de cada activo,
            revisar los rent rolls, gestionar la caja y consultar precios bursátiles.
        </div>
        <div>
            <span class="welcome-pill">📊 CDG mensual</span>
            <span class="welcome-pill">💰 NOI activos</span>
            <span class="welcome-pill">🏦 Caja</span>
            <span class="welcome-pill">📋 Rent Roll</span>
            <span class="welcome-pill">📈 Precios</span>
            <span class="welcome-pill">📁 EEFF</span>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# 2. Componente dinámico: Segundo elemento en el DOM. Cambia el CSS si hay mensajes.
if st.session_state.messages:
    st.markdown("""
    <style>
    .welcome-container { padding: 0rem 2rem 1.5rem 2rem !important; }
    .welcome-logo { font-size: 2.8rem !important; color: rgba(232, 227, 220, 0.85) !important; margin-bottom: 0 !important; }
    .welcome-fade-group { opacity: 0 !important; transform: translateY(-20px) !important; max-height: 0 !important; margin: 0 !important; pointer-events: none !important; }
    </style>
    """, unsafe_allow_html=True)
else:
    # Mantenemos el mismo orden en el Virtual DOM de Streamlit (índice 1)
    st.markdown("<style>/* Estado inicial */</style>", unsafe_allow_html=True)

for msg in st.session_state.messages:
    _avatar = _AGENT_AVATAR if msg["role"] == "assistant" else ":material/person:"
    with st.chat_message(msg["role"], avatar=_avatar):
        st.markdown(msg["content"])

# ─── Generar respuesta del asistente si corresponde ───────────────────────────
if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_msg_text = st.session_state.messages[-1]["content"]

    recent_history = " ".join([m["content"] for m in st.session_state.messages[-5:-1] if m["role"] == "user"])
    grupos = get_intent_groups(recent_history + " " + user_msg_text)
    selected_tools = _select_tools(grupos)
    
    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\n\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\n\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\n\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\n\n" + PROMPT_CAJA
    
    memory_block = load_memory()
    if memory_block:
        system_content += "\n\n---\n\n" + memory_block
    
    api_messages = [{"role": "system", "content": system_content}]
    
    history = [m for m in st.session_state.messages if m["role"] in ("user", "assistant")]
    for m in history[-(_MAX_HISTORY_TURNS * 2):]:
        api_messages.append({"role": m["role"], "content": m["content"]})
    
    tools_used = []
    final_response = ""

    _generation_container = st.empty()
    with _generation_container.container():
        with st.chat_message("assistant", avatar=_AGENT_AVATAR):
            status_area = st.empty()
            response_area = st.empty()
            tool_lines = []

        try:
            iteration = 0
            while True:
                iteration += 1
                if iteration > _MAX_TOOL_ITERS:
                    final_response = (
                        f"⚠️ Límite de {_MAX_TOOL_ITERS} rondas de herramientas alcanzado. "
                        "La tarea puede estar incompleta. Reformula la instrucción o divídela en pasos."
                    )
                    status_area.empty()
                    response_area.warning(final_response)
                    break

                response = _llm_call(
                    model=MODEL,
                    messages=api_messages,
                    tools=selected_tools,
                    tool_choice="auto",
                )
                msg = response.choices[0].message
                api_messages.append(msg)

                if not msg.tool_calls:
                    if msg.content:
                        final_response = msg.content
                    else:
                        # El modelo retornó contenido vacío tras tool calls — pedir resumen explícito
                        api_messages.append({"role": "user", "content": "Resume brevemente los resultados de lo que encontraste."})
                        followup = _llm_call(model=MODEL, messages=api_messages, tools=[], tool_choice="none")
                        final_response = followup.choices[0].message.content or "Sin respuesta del modelo."
                        
                    status_area.empty()
                    
                    # Simular tipeo
                    import time
                    def stream_text(text):
                        words = text.split(" ")
                        for i, word in enumerate(words):
                            yield word + (" " if i < len(words) - 1 else "")
                            time.sleep(0.035)  # Aumentado para que sea más lento y fluido
                            
                    with response_area:
                        st.write_stream(stream_text(final_response))
                        
                    break

                for tool_call in msg.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    tool_lines.append(f'<span class="tool-log-item">→ {name}</span>')
                    status_area.markdown(
                        '<div class="status-badge"><div class="status-dot"></div>Procesando...</div>'
                        + "".join(tool_lines),
                        unsafe_allow_html=True,
                    )
                    result = _dispatch(name, args)
                    if name not in tools_used:
                        tools_used.append(name)
                    api_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

        except RuntimeError as e:
            # _llm_call agotó los 5 reintentos (429 persistente)
            status_area.empty()
            final_response = str(e)
            response_area.error(
                "**Rate limit persistente.** La API de Gemini está saturada en este momento. "
                "Espera 1–2 minutos e intenta de nuevo.\n\n"
                f"Detalle técnico: `{e}`"
            )
        except Exception as e:
            status_area.empty()
            final_response = f"Error: {e}"
            response_area.error(f"**Error inesperado:** `{e}`")

    st.session_state.messages.append({"role": "assistant", "content": final_response})
    guardar_tarea(user_msg_text, tools_used, final_response[:200])
    st.rerun()
