import json
import streamlit as st

from agent import (
    client, MODEL, SYSTEM_PROMPT,
    _select_tools, _dispatch,
)
from tools.memory_tools import load_memory, guardar_tarea

# ─── Configuración de página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Agente Toesca",
    page_icon="🏢",
    layout="centered",
)

st.title("Agente Toesca")
st.caption("Control de Gestión · NOI · Caja · Rent Roll")

# ─── Estado de sesión ──────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []   # historial visible en el chat
if "api_messages" not in st.session_state:
    st.session_state.api_messages = []  # historial que va a la API


# ─── Mostrar historial ─────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


# ─── Input del usuario ─────────────────────────────────────────────────────────
user_input = st.chat_input("¿Qué necesitas hacer?")

if user_input:
    # Mostrar mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Preparar mensajes para la API (con memoria inyectada)
    memory_block = load_memory()
    system_content = SYSTEM_PROMPT
    if memory_block:
        system_content = SYSTEM_PROMPT + "\n\n---\n\n" + memory_block

    # Reconstruir historial API desde el historial visible
    api_messages = [{"role": "system", "content": system_content}]
    for m in st.session_state.messages:
        if m["role"] in ("user", "assistant"):
            api_messages.append({"role": m["role"], "content": m["content"]})

    selected_tools = _select_tools(user_input)
    n_selected = len(selected_tools)

    tools_used = []
    final_response = ""

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        response_placeholder = st.empty()

        # Info de herramientas activas
        status_placeholder.caption(f"Herramientas activas: {n_selected}/69")

        # ─── Loop de tool-calling ──────────────────────────────────────────────
        tool_log = []

        while True:
            response = client.chat.completions.create(
                model=MODEL,
                messages=api_messages,
                tools=selected_tools,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            api_messages.append(msg)

            # Sin tool calls → respuesta final
            if not msg.tool_calls:
                if msg.content:
                    final_response = msg.content
                break

            # Ejecutar tool calls
            for tool_call in msg.tool_calls:
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                tool_log.append(f"→ `{name}`")
                status_placeholder.markdown("\n".join(tool_log))

                result = _dispatch(name, args)

                if name not in tools_used:
                    tools_used.append(name)

                api_messages.append({
                    "role":         "tool",
                    "tool_call_id": tool_call.id,
                    "content":      result,
                })

        # Mostrar respuesta final
        status_placeholder.empty()
        if final_response:
            response_placeholder.markdown(final_response)
        else:
            final_response = "Tarea completada."
            response_placeholder.markdown(final_response)

    # Guardar en historial visible y en memoria
    st.session_state.messages.append({"role": "assistant", "content": final_response})
    guardar_tarea(user_input, tools_used, final_response[:200])
