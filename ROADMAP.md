# Roadmap — Agente Toesca

## Estado actual (Abril 2026)

- Agente Python con Gemini 2.5 Flash
- Interfaz: chat web local via Streamlit (`streamlit run app.py`)
- Herramientas: CDG, NOI, Caja, Rent Roll, EEFF, Fondos, Email, Memoria/KPIs, **Fact Sheets PPTX (PT/APO/TRI)**
- Selección dinámica de herramientas por intent en `registry.py` (~30-60% ahorro en tokens)
- Archivos leídos desde OneDrive sincronizado localmente

---

## Próximos pasos

### Urgente — Actualizaciones Críticas
- [ ] **Enseñar a actualizar dividendos en input PT:** Definir flujo de captura y validación de dividendos para Parque Titanium.
- [ ] **Enseñar planillas balances consolidados:** Documentar e implementar la lógica de actualización de balances consolidados.
- [ ] **Terminar de enseñar FS PT:** Completar la automatización y validación del Fact Sheet de Parque Titanium.
- [ ] **Enseñar a usar planilla resumen recaudación.**

### Corto plazo — Ajustes y Pruebas
- [x] Confirmar ruta exacta del archivo ER-FC INMOSA en SharePoint
- [x] Confirmar nombre del archivo TIR Fondo Rentas
- [x] Agregar `streamlit` a `requirements.txt`
- [x] Automatización Fact Sheets PPTX (PT, APO, TRI) — preparar, actualizar, guardar
- [ ] Probar flujo completo end-to-end con datos reales Q1 2026
- [ ] Actualización automática de gráficos en Fact Sheets (charts embebidos PPTX)

### Mediano plazo 1 — Multi-usuario en red interna
- [ ] Correr el agente en una PC fija de la oficina (Windows, con Outlook y OneDrive) o servidor en red.
- [ ] Exponer Streamlit en la red interna (`http://192.168.x.x:8501`)
- [ ] Agregar autenticación simple (usuario/contraseña) para controlar acceso
- [ ] Separar memoria por usuario (hoy es una sola memoria compartida) migrando a SQLite o PostgreSQL.
- [ ] Sistema de usuarios con perfil de cargo
      → Cada usuario tiene nombre, cargo y permisos asociados
      → El agente adapta sus respuestas según el rol (ej: analista vs gerente)
      → El cargo determina qué fondos y herramientas puede usar cada persona
      → Registro de quién hizo qué en el historial de tareas

### Mediano plazo 2 — Inteligencia de Activos y Nueva Arquitectura
- [ ] **Arquitectura Multi-Agente (Sub-agentes):** Migrar el enrutador actual a un framework de sub-agentes (ej. LangGraph o CrewAI) para evitar sobrecarga del LLM y dividir tareas especializadas (Agente Financiero, Agente Presentador, Agente de Datos).
- [ ] **RAG (Retrieval-Augmented Generation) para Documentos:** Implementar Base de Datos Vectorial (ej. Chroma, Pinecone) para indexar, buscar e interpretar contratos y memorándums corporativos en tiempo real.
- [ ] **Consultas Estructuradas Dinámicas:** Incorporar Text-to-SQL o agentes de Pandas para que pueda responder preguntas analíticas cruzadas sin depender de prompts pre-programados.

### Largo plazo — Escalamiento, Dashboards y Presentaciones
- [ ] Migrar acceso a archivos de "disco local" a "SharePoint vía Microsoft Graph API"
      → Permite subir el agente a la nube (Azure, AWS, etc.)
      → Cualquier persona del equipo lo usa desde el navegador sin instalar nada
      → Requiere reemplazar `sharepoint_tools.py` y `local_tools.py`
- [ ] Autenticación con cuentas corporativas (Microsoft SSO / Azure AD)
- [ ] **Dashboards interactivos en Streamlit:** Capacidad del agente de generar y renderizar gráficos dinámicos (Plotly/Altair) en la interfaz de chat según lo que se le pida.
- [ ] Dashboard fijo de KPIs: visualización de tendencias registradas en `kpis.jsonl`, comparación entre períodos.
- [ ] **Exportación Automática a PPTX:** Crear una herramienta con `python-pptx` para que el agente pueda redactar resúmenes financieros y entregar diapositivas listas para descargar.
- [ ] Generación automática del CDG mensual como tarea programada
      → El agente corre solo el primer día hábil del mes
      → Notifica por email cuando termina
- [ ] Expandir a otros reportes (ej: reporte de vacancia, reporte de distribuciones)
