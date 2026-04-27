import sys

def refactor():
    with open('c:/Users/raimundo.opazo/automation_agent/agent.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    import_lines = []
    registry_lines = []
    agent_lines = []
    
    in_tools_import = False
    in_tool_defs = False
    in_dispatch = False
    in_select_tools = False
    in_tool_groups = False
    
    # We will also move _MAX_TOOL_RESULT because _dispatch uses it
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Capture from tools.xxx import (...)
        if line.startswith('from tools.') and 'import' in line:
            in_tools_import = True
            import_lines.append(line)
            i += 1
            continue
            
        if in_tools_import:
            if line.startswith('from ') or line.startswith('import '):
                in_tools_import = False # finished block
            else:
                import_lines.append(line)
                i += 1
                continue
                
        # capture _MAX_TOOL_RESULT
        if line.startswith('_MAX_TOOL_RESULT'):
            registry_lines.append(line)
            i += 1
            continue
            
        # capture TOOL_DEFINITIONS
        if line.startswith('TOOL_DEFINITIONS = ['):
            in_tool_defs = True
            registry_lines.append(line)
            i += 1
            continue
            
        if in_tool_defs:
            registry_lines.append(line)
            if line.startswith(']'):
                in_tool_defs = False
            i += 1
            continue
            
        # capture _dispatch
        if line.startswith('def _dispatch('):
            in_dispatch = True
            registry_lines.append(line)
            i += 1
            continue
            
        if in_dispatch:
            registry_lines.append(line)
            if line.startswith('def _select_tools'):
                in_dispatch = False
            elif line.startswith('# ─── Selección dinámica') or line.startswith('_TOOLS_GENERAL ='):
                in_dispatch = False
            else:
                i += 1
                continue
                
        # capture _TOOLS_GENERAL and groups
        if line.startswith('_TOOLS_GENERAL ='):
            in_tool_groups = True
            registry_lines.append(line)
            i += 1
            continue
            
        if in_tool_groups:
            registry_lines.append(line)
            if line.startswith('def _select_tools'):
                in_tool_groups = False
            else:
                i += 1
                continue
                
        # capture _select_tools
        if line.startswith('def _select_tools('):
            in_select_tools = True
            registry_lines.append(line)
            i += 1
            continue
            
        if in_select_tools:
            registry_lines.append(line)
            if line.startswith('# ─── Runner principal'):
                in_select_tools = False
            elif line.startswith('def run_agent('):
                in_select_tools = False
            else:
                i += 1
                continue
                
        # If we reach here, it belongs to agent.py
        if not line.startswith('# ─── Definición de herramientas') and not line.startswith('# ─── Despachador de herramientas') and not line.startswith('# ─── Selección dinámica de herramientas'):
            agent_lines.append(line)
        i += 1

    registry_content = "import json\n"
    registry_content += "".join(import_lines)
    registry_content += "\n" + "".join(registry_lines)
    
    with open('c:/Users/raimundo.opazo/automation_agent/tools/registry.py', 'w', encoding='utf-8') as f:
        f.write(registry_content)
        
    # add import to agent_lines
    insert_idx = 0
    for idx, l in enumerate(agent_lines):
        if l.startswith('from config import GEMINI_API_KEY'):
            insert_idx = idx + 1
            break
            
    agent_lines.insert(insert_idx, "from tools.registry import TOOL_DEFINITIONS, _dispatch, _select_tools\n")
    
    with open('c:/Users/raimundo.opazo/automation_agent/agent.py', 'w', encoding='utf-8') as f:
        f.writelines(agent_lines)

if __name__ == '__main__':
    refactor()
