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

import random
from agent import (
    client, MODEL, BASE_PROMPT, PROMPT_CDG, PROMPT_NOI, PROMPT_RENTROLL, PROMPT_CAJA,
    _select_tools, _dispatch, _llm_call, get_intent_groups, _trim_tool_messages,
    _MAX_TOOL_ITERS, _thinking_phrase, _sanitize_messages_for_api,
    _try_revisar_respuesta_contacto_directo,
)
from tools.ask_tools import set_streamlit_mode, _SENTINEL_PREFIX
set_streamlit_mode(True)

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
st.iframe("""
<script>
(function() {
    var parentDoc = window.parent.document;
    var frame = window.frameElement;
    var buttonId = 'toesca-sidebar-btn';
    var styleId = 'toesca-sidebar-style';

    if (frame) {
        frame.style.position = 'absolute';
        frame.style.width = '0';
        frame.style.height = '0';
        frame.style.border = '0';
        frame.style.visibility = 'hidden';
    }

    function ensureButton() {
        if (!parentDoc.getElementById(styleId)) {
            var style = parentDoc.createElement('style');
            style.id = styleId;
            style.textContent = `
                #${buttonId} {
                    position: fixed; top: 12px; left: 12px; z-index: 99999;
                    width: 30px; height: 30px;
                    background: #141414; border: 1px solid #252525; border-radius: 5px;
                    display: flex; align-items: center; justify-content: center;
                    cursor: pointer; color: #666; font-size: 13px; line-height: 1;
                    transition: color .15s, border-color .15s; user-select: none;
                    padding: 0; font-family: Arial, sans-serif;
                }
                #${buttonId}:hover { color: #e8e3dc; border-color: #555; }
            `;
            parentDoc.head.appendChild(style);
        }

        var btn = parentDoc.getElementById(buttonId);
        if (!btn) {
            btn = parentDoc.createElement('button');
            btn.id = buttonId;
            btn.type = 'button';
            btn.title = 'Mostrar/ocultar barra lateral';
            btn.setAttribute('aria-label', 'Mostrar/ocultar barra lateral');
            btn.innerHTML = '&#9776;';
            parentDoc.body.appendChild(btn);
        }

        btn.onclick = toggleSidebar;
    }

    function clickIfFound(selector) {
        var matches = parentDoc.querySelectorAll(selector);
        for (var k = 0; k < matches.length; k++) {
            var el = matches[k];
            var target = el.tagName === 'BUTTON' ? el : el.querySelector('button') || el;
            if (target.id === buttonId || el.id === buttonId) continue;

            target.click();
            return true;
        }
        return false;
    }
    
    function toggleSidebar() {
        var selectors = [
            '[data-testid="stSidebarCollapseButton"]',
            '[data-testid="stSidebarCollapsedControl"]',
            '[data-testid="collapsedControl"]',
            'button[kind="headerNoPadding"]',
            'button[data-testid="baseButton-headerNoPadding"]',
            'button[data-testid="stBaseButton-headerNoPadding"]',
            'button[aria-label*="sidebar" i]',
            'button[aria-label*="barra lateral" i]',
            'button[aria-label*="menu" i]',
            'button[title*="sidebar" i]',
            'button[title*="barra lateral" i]'
        ];

        for (var i = 0; i < selectors.length; i++) {
            if (clickIfFound(selectors[i])) return;
        }

        var candidates = parentDoc.querySelectorAll('button, [role="button"], [data-testid]');
        for (var j = 0; j < candidates.length; j++) {
            if (candidates[j].id === buttonId) continue;

            var aria = (candidates[j].getAttribute('aria-label') || '').toLowerCase();
            var testid = (candidates[j].getAttribute('data-testid') || '').toLowerCase();
            var title = (candidates[j].getAttribute('title') || '').toLowerCase();
            var text = (candidates[j].textContent || '').toLowerCase();
            var label = aria + ' ' + testid + ' ' + title + ' ' + text;

            if (
                label.includes('sidebar') ||
                label.includes('barra lateral') ||
                label.includes('collapse') ||
                label.includes('expand') ||
                label.includes('menu')
            ) {
                candidates[j].click();
                return;
            }
        }

        var header = parentDoc.querySelector('header');
        if (header) {
            var btn = header.querySelector('button');
            if (btn) { btn.click(); return; }
        }
    }
    
    ensureButton();
    var observer = new MutationObserver(ensureButton);
    observer.observe(parentDoc.body, { childList: true, subtree: true });
})();
</script>
""", width="content", height=1)



# ─── Estado ────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None
if "show_balance_quick_actions" not in st.session_state:
    st.session_state.show_balance_quick_actions = False


def _queue_quick_action(instruction: str):
    st.session_state.pending_input = instruction
    st.rerun()

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="toesca-logo">toesca.</p>', unsafe_allow_html=True)
    st.markdown('<p class="toesca-tagline">Gestión de Fondos</p>', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:13px; color:#888; padding-bottom:10px;">👤 {st.session_state.get("name", "")}</div>', unsafe_allow_html=True)
    authenticator.logout('Cerrar Sesión', 'main')
    
    st.markdown('<hr class="sidebar-divider">', unsafe_allow_html=True)

    st.markdown('<p class="sidebar-section">Acciones rápidas</p>', unsafe_allow_html=True)

    if st.button("📊  Actualizar CDG", key="qa_actualizar_cdg"):
        _queue_quick_action(
            "Actualizar CDG. Primero llama verificar_archivos_cdg(año, mes). "
            "Si hay archivos faltantes, detente y muestra el resultado completo con encontrados y faltantes. "
            "Si no falta nada, actualiza el CDG siguiendo el flujo mensual completo y guarda el archivo vAgente. "
            "Si el periodo no esta claro, preguntame mes y año antes de ejecutar."
        )

    if st.button("📥  Digerir RAW files", key="qa_digerir_raw"):
        _queue_quick_action(
            "Digerir RAW files. Revisa que hay en la carpeta RAW de SharePoint y ordenalo de forma inteligente. "
            "Llama ordenar_archivos_raw() y muestra el resultado completo, incluyendo archivos movidos y no reconocidos."
        )

    if st.button("📚  Actualizar balances consolidados", key="qa_balances_toggle"):
        st.session_state.show_balance_quick_actions = not st.session_state.show_balance_quick_actions
        st.rerun()

    if st.session_state.show_balance_quick_actions:
        balance_actions = [
            (
                "Balance consolidado Apoquindo",
                "Actualizar Balance Consolidado Apoquindo. Si el periodo no esta claro, preguntame mes y año. "
                "Despues usa actualizar_balance_consolidado_apoquindo_si_completo(mes, año), que debe verificar faltantes primero "
                "y solo actualizar si no falta nada."
            ),
            (
                "Balance consolidado PT",
                "Actualizar Balance Consolidado PT. Si el periodo no esta claro, preguntame mes y año. "
                "Despues usa actualizar_balance_consolidado_pt_si_completo(mes, año), que debe verificar faltantes primero "
                "y solo actualizar si no falta nada."
            ),
            (
                "Balance consolidado Rentas",
                "Actualizar Balance Consolidado Rentas. Si el periodo no esta claro, preguntame mes y año. "
                "Despues usa actualizar_balance_consolidado_rentas_si_completo(mes, año) y reporta honestamente el estado."
            ),
            (
                "Todos",
                "Actualizar todos los balances consolidados. Si el periodo no esta claro, preguntame mes y año. "
                "Despues usa actualizar_balances_consolidados_si_completos(mes, año), verificando cada balance antes de actualizarlo."
            ),
        ]
        for label, instruction in balance_actions:
            if st.button(f"   {label}", key=f"qa_{label}"):
                _queue_quick_action(instruction)

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
chat_input = st.chat_input("Escribe una instrucción...")
user_input = chat_input or _pending
is_internal_action = bool(_pending and not chat_input)

if _pending:
    st.session_state.pending_input = None

if user_input and not is_internal_action:
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
has_chat_activity = bool(st.session_state.messages) or bool(user_input)
if has_chat_activity:
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
should_generate_response = bool(user_input) and (
    is_internal_action
    or (st.session_state.messages and st.session_state.messages[-1]["role"] == "user")
)
if should_generate_response:
    user_msg_text = user_input

    if "pending_resume" not in st.session_state:
        direct_response = _try_revisar_respuesta_contacto_directo(user_msg_text)
        if direct_response is not None:
            with st.chat_message("assistant", avatar=_AGENT_AVATAR):
                st.markdown(direct_response)
            st.session_state.messages.append({"role": "assistant", "content": direct_response})
            guardar_tarea(user_msg_text, ["revisar_respuestas_contacto"], direct_response[:200])
            st.rerun()

    def _serialize_messages(messages):
        return _sanitize_messages_for_api(messages)

    # ─── Retomar tarea interrumpida por preguntar_usuario ─────────────────────
    if "pending_resume" in st.session_state:
        resume = st.session_state.pop("pending_resume")
        api_messages = resume["api_messages"]
        api_messages.append({
            "role": "tool",
            "tool_call_id": resume["pending_tool_call_id"],
            "content": user_msg_text,
        })
        grupos = set(resume["grupos"])
        selected_tools = resume["selected_tools"]
    else:
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
        if is_internal_action:
            api_messages.append({"role": "user", "content": user_msg_text})

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

                api_messages = _trim_tool_messages(api_messages)
                _phrase = _thinking_phrase(grupos)
                status_area.markdown(
                    f'<div class="status-badge"><div class="status-dot"></div>{_phrase}...</div>',
                    unsafe_allow_html=True,
                )
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
                        api_messages.append({"role": "user", "content": "Resume brevemente los resultados de lo que encontraste."})
                        followup = _llm_call(model=MODEL, messages=api_messages, tools=[], tool_choice="none")
                        final_response = followup.choices[0].message.content or "Sin respuesta del modelo."

                    status_area.empty()
                    with response_area:
                        st.markdown(final_response)
                    break

                ask_user_triggered = False
                direct_tool_response = False
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

                    # Agente pide ayuda al usuario — pausar y retomar en el próximo turno
                    if result.startswith(_SENTINEL_PREFIX):
                        pregunta = result[len(_SENTINEL_PREFIX):]
                        st.session_state["pending_resume"] = {
                            "api_messages": _serialize_messages(api_messages),
                            "pending_tool_call_id": tool_call.id,
                            "grupos": list(grupos),
                            "selected_tools": selected_tools,
                        }
                        final_response = pregunta
                        ask_user_triggered = True
                        break

                    if name not in tools_used:
                        tools_used.append(name)
                    api_messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

                    if name in {
                        "revisar_respuestas_contacto",
                        "verificar_archivos_cdg",
                        "ordenar_archivos_raw",
                        "previsualizar_correos_solicitud_cdg",
                        "enviar_correos_solicitud_cdg",
                    }:
                        final_response = result
                        direct_tool_response = True
                        break

                if ask_user_triggered:
                    status_area.empty()
                    with response_area:
                        st.markdown(final_response)
                    break

                if direct_tool_response:
                    status_area.empty()
                    with response_area:
                        st.markdown(final_response)
                    break

        except RuntimeError as e:
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
