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
import streamlit.components.v1 as components

if st.session_state.get("authentication_status") is True:
    if "loader_start_time" not in st.session_state:
        st.session_state.loader_start_time = time.time()

    if time.time() - st.session_state.loader_start_time < 3.5:
        # Inyectamos el loader directamente en el DOM raíz (fuera de React)
        # Esto evita que Streamlit destruya o reinicie la animación durante los reruns
        components.html("""
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
        """, width=0, height=0)

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
    
    # Reiniciar la pantalla de carga para que la transición ocurra siempre al loguearse
    if "loader_start_time" in st.session_state:
        del st.session_state["loader_start_time"]
        
    # Inyectamos algo de CSS global básico para ocultar sidebar antes de login
    st.markdown("""
    <style>
    [data-testid="collapsedControl"] { display: none !important; }
    [data-testid="stSidebar"] { display: none !important; }
    </style>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
        <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
        
        <style>
        /* Animaciones Globales del Login */
        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes formEntrance {
            from { opacity: 0; transform: translate3d(0, 30px, 0); }
            to { opacity: 1; transform: translate3d(0, 0, 0); }
        }
        
        .login-header-wrapper {
            animation: fadeInDown 0.8s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
        }

        /* Glassmorphism premium para el form de login */
        div[data-testid="stForm"] {
            background: linear-gradient(135deg, rgba(25, 25, 25, 0.7), rgba(10, 10, 10, 0.9)) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-top: 1px solid rgba(255, 255, 255, 0.18) !important; /* Efecto luz cenital */
            border-radius: 16px !important;
            padding: 3rem 2.5rem !important;
            backdrop-filter: blur(25px) saturate(150%) !important;
            -webkit-backdrop-filter: blur(25px) saturate(150%) !important;
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.8), inset 0 0 0 1px rgba(255, 255, 255, 0.02) !important;
            
            /* Animación de entrada y Fix de Chrome */
            opacity: 0; /* Comienza invisible para la animación */
            animation: formEntrance 0.8s cubic-bezier(0.2, 0.8, 0.2, 1) 0.2s forwards !important;
            backface-visibility: hidden !important;
            -webkit-backface-visibility: hidden !important;
        }

        /* Labels de los inputs más corporativos y limpios */
        div[data-testid="stForm"] label {
            color: #a3a3a3 !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.1em !important;
            text-transform: uppercase !important;
            margin-bottom: 0.5rem !important;
        }

        /* Cajas de texto premium */
        div[data-testid="stForm"] input {
            background-color: rgba(0, 0, 0, 0.4) !important;
            color: #ffffff !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 8px !important;
            padding: 0.85rem 1.2rem !important;
            font-size: 0.95rem !important;
            font-family: 'Inter', sans-serif !important;
            transition: all 0.3s ease !important;
            box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.2) !important;
        }

        /* Focus en cajas de texto (Acento Corporativo Dorado/Toesca) */
        div[data-testid="stForm"] input:focus {
            border-color: #c9a84c !important;
            background-color: rgba(0, 0, 0, 0.6) !important;
            box-shadow: 0 0 0 1px #c9a84c, inset 0 2px 4px rgba(0, 0, 0, 0.3) !important;
            outline: none !important;
        }

        div[data-testid="stForm"] input::placeholder {
            color: rgba(255, 255, 255, 0.2) !important;
        }

        /* Botón de Iniciar Sesión Elevado */
        div[data-testid="stForm"] button {
            background: linear-gradient(135deg, #e8e3dc, #c4beaf) !important;
            color: #111111 !important;
            border: none !important;
            font-weight: 600 !important;
            font-family: 'Inter', sans-serif !important;
            font-size: 0.95rem !important;
            letter-spacing: 0.02em !important;
            border-radius: 8px !important;
            padding: 0.85rem !important;
            transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1) !important;
            margin-top: 1.5rem !important;
            box-shadow: 0 4px 15px rgba(232, 227, 220, 0.15) !important;
            width: 100% !important;
        }

        /* Hover de Botón */
        div[data-testid="stForm"] button:hover {
            background: linear-gradient(135deg, #ffffff, #e8e3dc) !important;
            transform: translateY(-3px) !important;
            box-shadow: 0 8px 25px rgba(232, 227, 220, 0.3) !important;
        }
        
        /* Click de Botón */
        div[data-testid="stForm"] button:active {
            transform: translateY(0px) !important;
            box-shadow: 0 2px 10px rgba(232, 227, 220, 0.2) !important;
        }

        /* Ajustes Opcionales Streamlit */
        .stMarkdown p { font-family: 'Inter', sans-serif !important; }
        </style>
        
        <div class="login-header-wrapper" style="text-align: center; margin-top: 8vh; margin-bottom: 2.5rem;">
            <div style="font-family: 'EB Garamond', Georgia, serif; font-size: 5.5rem; color: #e8e3dc; line-height: 1;">toesca.</div>
            <div style="font-family: 'Inter', sans-serif; font-size: 0.85rem; font-weight: 400; letter-spacing: 0.25em; text-transform: uppercase; color: #ffffff; margin-bottom: 2rem; margin-top: 0.8rem; opacity: 0.9;">Gestión de Fondos</div>
            <p style="color: #a0a0a0; font-family: 'Inter', sans-serif; font-size: 0.95rem; line-height: 1.6; font-weight: 300; max-width: 400px; margin: 0 auto;">
                Bienvenido al <b>Agente Toesca</b>.<br>Ingrese sus credenciales corporativas para acceder 
                al entorno automatizado.
            </p>
        </div>
        """, unsafe_allow_html=True)

        try:
            # Login location se pone en 'main'
            authenticator.login('main')
        except Exception as e:
            st.error(e)

        if st.session_state.get("authentication_status") is False:
            st.error('Usuario o contraseña incorrectos.')
    
    if st.session_state.get("authentication_status") is True:
        st.rerun()
    else:
        # Detenemos la ejecución de la app si no se ha logueado exitosamente
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

import streamlit.components.v1 as components
components.html("""
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
""", width=0, height=0)



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

# ─── Área principal ────────────────────────────────────────────────────────────
if not st.session_state.messages:
    st.markdown("""
    <div class="welcome-container">
        <div class="welcome-logo">toesca.</div>
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
    """, unsafe_allow_html=True)
else:
    for msg in st.session_state.messages:
        _avatar = _AGENT_AVATAR if msg["role"] == "assistant" else ":material/person:"
        with st.chat_message(msg["role"], avatar=_avatar):
            st.markdown(msg["content"])

# ─── Procesar input ────────────────────────────────────────────────────────────
_pending = st.session_state.get("pending_input")
if _pending:
    st.session_state.pending_input = None

user_input = st.chat_input("Escribe una instrucción...") or _pending

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(user_input)

    recent_history = " ".join([m["content"] for m in st.session_state.messages[-4:] if m["role"] == "user"])
    grupos = get_intent_groups(recent_history + " " + user_input)
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
    # Solo los últimos N turnos para evitar acumulación de tokens en sesiones largas
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
                            time.sleep(0.015)
                            
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
    guardar_tarea(user_input, tools_used, final_response[:200])
