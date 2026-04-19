import json
import streamlit as st
from pathlib import Path

from agent import (
    client, MODEL, SYSTEM_PROMPT,
    _select_tools, _dispatch,
)
from tools.memory_tools import load_memory, guardar_tarea

# ─── Página ────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Agente Toesca", page_icon="🏢", layout="wide")

# ─── Inyectar CSS desde archivo externo ───────────────────────────────────────
css = Path("style.css").read_text()
st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

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
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

# ─── Procesar input ────────────────────────────────────────────────────────────
_pending = st.session_state.get("pending_input")
if _pending:
    st.session_state.pending_input = None

user_input = st.chat_input("Escribe una instrucción...") or _pending

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    memory_block = load_memory()
    system_content = SYSTEM_PROMPT + ("\n\n---\n\n" + memory_block if memory_block else "")
    api_messages = [{"role": "system", "content": system_content}]
    for m in st.session_state.messages:
        if m["role"] in ("user", "assistant"):
            api_messages.append({"role": m["role"], "content": m["content"]})

    selected_tools = _select_tools(user_input)
    tools_used = []
    final_response = ""

    with st.chat_message("assistant"):
        status_area = st.empty()
        response_area = st.empty()
        tool_lines = []

        while True:
            response = client.chat.completions.create(
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

    st.session_state.messages.append({"role": "assistant", "content": final_response})
    guardar_tarea(user_input, tools_used, final_response[:200])
