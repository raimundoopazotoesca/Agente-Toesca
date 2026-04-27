def patch_registry():
    with open('c:/Users/raimundo.opazo/automation_agent/tools/registry.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        if line.startswith('def _select_tools(user_input: str) -> list:'):
            # Change the signature to return tuple
            lines[i] = 'def _select_tools(user_input: str) -> tuple:\n'
            # Check if next line is identical
            if i+1 < len(lines) and lines[i+1].startswith('def _select_tools'):
                lines[i+1] = '' # remove duplicate
            
        if line.startswith('    return selected'):
            # change return to return (selected, grupos)
            lines[i] = '    return (selected, grupos)\n'
            
        if line.startswith('        return [_TOOL_INDEX[n] for n in _TOOLS_GENERAL if n in _TOOL_INDEX]'):
            lines[i] = '        return ([_TOOL_INDEX[n] for n in _TOOLS_GENERAL if n in _TOOL_INDEX], grupos)\n'
            
    with open('c:/Users/raimundo.opazo/automation_agent/tools/registry.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)

if __name__ == '__main__':
    patch_registry()
