_SENTINEL_PREFIX = "__PREGUNTA_USUARIO__|"
_streamlit_mode = False


def set_streamlit_mode(enabled: bool = True) -> None:
    global _streamlit_mode
    _streamlit_mode = enabled


def preguntar_usuario(pregunta: str) -> str:
    if _streamlit_mode:
        return _SENTINEL_PREFIX + pregunta
    print(f"\n❓ {pregunta}")
    respuesta = input("  Tu respuesta: ").strip()
    return respuesta or "(sin respuesta)"
