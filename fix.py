import re

with open('agent.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix print statement
content = content.replace('print("\\n" + "=" * 60)', 'print("\\n" + "=" * 60)')

# Use regex to fix the system_content block
fixed = """def run_agent(user_input: str) -> None:
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

# Replace from def run_agent to final_response = ""
pattern = re.compile(r'def run_agent\(user_input: str\) -> None:.*?final_response = ""\n', re.DOTALL)
content = pattern.sub(fixed, content)

with open('agent.py', 'w', encoding='utf-8') as f:
    f.write(content)
