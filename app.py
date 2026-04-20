import json
import streamlit as st
from pathlib import Path

from agent import (
    client, MODEL, SYSTEM_PROMPT,
    _select_tools, _dispatch, _llm_call,
    _MAX_TOOL_ITERS,
)

_MAX_HISTORY_TURNS = 3   # pares usuario/agente a mantener en contexto
from tools.memory_tools import load_memory, guardar_tarea

# ─── Página ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente Toesca",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Inyectar CSS desde archivo externo ───────────────────────────────────────
css = Path("style.css").read_text()
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

# ─── Pantalla de carga (solo en el primer render) ─────────────────────────────
if "loader_shown" not in st.session_state:
    st.session_state.loader_shown = True
    st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400&display=swap" rel="stylesheet">
<div id="toesca-loader">
  <div class="tl-content">
    <div class="tl-logo">
      <span class="tl-text">toesca</span><span class="tl-dot">.</span>
    </div>
  </div>
  <div class="tl-bar"><div class="tl-progress"></div></div>
</div>

<style>
#toesca-loader {
  position: fixed;
  inset: 0;
  background: #0a0a0a;
  z-index: 99999;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  animation: tl-fadeout 0.6s cubic-bezier(0.4,0,1,1) 2.9s forwards;
}
.tl-content {
  display: flex;
  align-items: center;
  justify-content: center;
}
.tl-logo {
  font-family: 'EB Garamond', Georgia, serif;
  font-size: 5rem;
  font-weight: 400;
  color: #e8e3dc;
  display: flex;
  align-items: baseline;
  line-height: 1;
  overflow: visible;
  position: relative;
}
.tl-text {
  opacity: 0;
  animation: tl-textin 0.8s ease-out 0.2s forwards;
}
.tl-dot {
  display: inline-block;
  opacity: 0;
  transform: translateX(-48vw);
  animation: tl-dotin 1.0s cubic-bezier(0.34,1.45,0.64,1) 1.2s forwards;
  color: #e8e3dc;
}
.tl-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 1px;
  background: #1a1a1a;
}
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

<script>
setTimeout(function() {
  var el = document.getElementById('toesca-loader');
  if (el) el.remove();
}, 3500);
</script>
""", unsafe_allow_html=True)

# ─── Estado ────────────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None

# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="toesca-logo">toesca.</p>', unsafe_allow_html=True)
    st.markdown('<p class="toesca-tagline">Gestión de Fondos</p>', unsafe_allow_html=True)
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
    for f in ["A&R Apoquindo", "A&R PT", "A&R Rentas"]:
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
        _avatar = ":material/apartment:" if msg["role"] == "assistant" else ":material/person:"
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

    memory_block = load_memory()
    system_content = SYSTEM_PROMPT + ("\n\n---\n\n" + memory_block if memory_block else "")
    api_messages = [{"role": "system", "content": system_content}]
    # Solo los últimos N turnos para evitar acumulación de tokens en sesiones largas
    history = [m for m in st.session_state.messages if m["role"] in ("user", "assistant")]
    for m in history[-(_MAX_HISTORY_TURNS * 2):]:
        api_messages.append({"role": m["role"], "content": m["content"]})

    selected_tools = _select_tools(user_input)
    tools_used = []
    final_response = ""

    with st.chat_message("assistant", avatar=":material/apartment:"):
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
                    final_response = msg.content or "Tarea completada."
                    status_area.empty()
                    response_area.markdown(final_response)
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
