def patch_registry():
    with open('c:/Users/raimundo.opazo/automation_agent/tools/registry.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    import re
    old_func_pattern = re.compile(r'def _select_tools\(user_input: str\) -> tuple:.*?return \(\[_TOOL_INDEX\[n\] for n in nombres if n in _TOOL_INDEX\], grupos\)', re.DOTALL)
    
    new_func = """def _select_tools(grupos: set) -> list:
    if not grupos:
        return [_TOOL_INDEX[n] for n in _TOOLS_GENERAL if n in _TOOL_INDEX]

    nombres = set(_TOOLS_GENERAL)
    if "cdg"      in grupos: nombres |= _TOOLS_CDG
    if "noi"      in grupos: nombres |= _TOOLS_NOI
    if "caja"     in grupos: nombres |= _TOOLS_CAJA
    if "rentroll" in grupos: nombres |= _TOOLS_RENTROLL

    return [_TOOL_INDEX[n] for n in nombres if n in _TOOL_INDEX]"""
    
    content = old_func_pattern.sub(new_func, content)
    with open('c:/Users/raimundo.opazo/automation_agent/tools/registry.py', 'w', encoding='utf-8') as f:
        f.write(content)

def patch_agent():
    with open('c:/Users/raimundo.opazo/automation_agent/agent.py', 'r', encoding='utf-8') as f:
        content = f.read()

    router_code = """
def get_intent_groups(history_text: str) -> set:
    prompt = f\"\"\"Dado el historial de chat con un asistente que automatiza tareas de un fondo de inversión inmobiliario, clasifica la intención del usuario.
Responde ÚNICAMENTE con una lista JSON válida de strings (ejemplo: ["cdg", "noi"]).
Las categorías permitidas son:
- "cdg" (Control de Gestión, planillas, archivos, actualizar control, tirar reportes)
- "noi" (NOI, Viña, Curicó, JLL, INMOSA, Apoquindo)
- "caja" (Saldo Caja, FFMM, archivar caja)
- "rentroll" (Rent Roll, vacancia, absorción)
Si no aplica ninguna, responde [].

Historial de conversación:
{history_text}
\"\"\"
    try:
        response = _llm_call(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        msg_content = response.choices[0].message.content.strip()
        if msg_content.startswith("```json"): msg_content = msg_content[7:-3].strip()
        elif msg_content.startswith("```"): msg_content = msg_content[3:-3].strip()
        
        import json
        grupos_list = json.loads(msg_content)
        return set(grupos_list)
    except Exception as e:
        print(f"[LLM Router Error] {e}")
        return set()

def run_agent(user_input: str) -> None:
    print("\\n" + "=" * 60)
    print(f"Instrucción: {user_input}")
    print("=" * 60)

    grupos = get_intent_groups(user_input)
    selected_tools = _select_tools(grupos)

    system_content = BASE_PROMPT
    if "cdg" in grupos: system_content += "\\n\\n" + PROMPT_CDG
    if "noi" in grupos: system_content += "\\n\\n" + PROMPT_NOI
    if "rentroll" in grupos: system_content += "\\n\\n" + PROMPT_RENTROLL
    if "caja" in grupos: system_content += "\\n\\n" + PROMPT_CAJA

    from tools.memory_tools import load_memory
    memory_block = load_memory()
    if memory_block:
        system_content += "\\n\\n---\\n\\n" + memory_block

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": user_input},
    ]

    tools_used = []
    final_response = ""
"""
    
    import re
    # We want to replace the whole `run_agent` setup down to `tools_used = []\n    final_response = ""`
    pattern = re.compile(r'def run_agent\(user_input: str\) -> None:.*?final_response = ""\s*selected_tools, grupos = _select_tools\(user_input\)', re.DOTALL)
    
    content = pattern.sub(router_code, content)
    with open('c:/Users/raimundo.opazo/automation_agent/agent.py', 'w', encoding='utf-8') as f:
        f.write(content)

def patch_app():
    with open('c:/Users/raimundo.opazo/automation_agent/app.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Import get_intent_groups
    content = content.replace("_select_tools, _dispatch, _llm_call,", "_select_tools, _dispatch, _llm_call, get_intent_groups,")
    
    old_call = "selected_tools, grupos = _select_tools(user_input)"
    new_call = """recent_history = " ".join([m["content"] for m in st.session_state.messages[-4:] if m["role"] == "user"])
    grupos = get_intent_groups(recent_history + " " + user_input)
    selected_tools = _select_tools(grupos)"""
    
    content = content.replace(old_call, new_call)
    
    with open('c:/Users/raimundo.opazo/automation_agent/app.py', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    patch_registry()
    patch_agent()
    patch_app()
