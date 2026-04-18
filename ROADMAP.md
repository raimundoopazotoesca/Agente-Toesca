# Roadmap — Agente Toesca

## Estado actual (Abril 2026)

- Agente Python con Gemini 2.5 Flash
- Interfaz: chat web local via Streamlit (`streamlit run app.py`)
- Herramientas: CDG, NOI, Caja, Rent Roll, EEFF, Fondos, Email, Memoria/KPIs
- Selección dinámica de herramientas por tarea (~30-60% ahorro en tokens)
- Archivos leídos desde OneDrive sincronizado localmente

---

## Próximos pasos

### Corto plazo

- [ ] Confirmar ruta exacta del archivo ER-FC INMOSA en SharePoint
- [ ] Confirmar nombre del archivo TIR Fondo Rentas
- [ ] Probar el flujo completo de febrero 2026 end-to-end
- [ ] Agregar `streamlit` a `requirements.txt`

### Mediano plazo — Multi-usuario en red interna

- [ ] Correr el agente en una PC fija de la oficina (Windows, con Outlook y OneDrive)
- [ ] Exponer Streamlit en la red interna (`http://192.168.x.x:8501`)
- [ ] Agregar autenticación simple (usuario/contraseña) para controlar acceso
- [ ] Separar memoria por usuario (hoy es una sola memoria compartida)

### Largo plazo — Escalamiento al equipo completo

- [ ] Migrar acceso a archivos de "disco local" a "SharePoint vía Microsoft Graph API"
      → Permite subir el agente a la nube (Azure, AWS, etc.)
      → Cualquier persona del equipo lo usa desde el navegador sin instalar nada
      → Requiere reemplazar `sharepoint_tools.py` y `local_tools.py`

- [ ] Autenticación con cuentas corporativas (Microsoft SSO / Azure AD)

- [ ] Dashboard de KPIs: visualización de los KPIs registrados en `kpis.jsonl`
      → Gráficos de tendencia por fondo y período
      → Comparación entre períodos directamente en la interfaz

- [ ] Generación automática del CDG mensual como tarea programada
      → El agente corre solo el primer día hábil del mes
      → Notifica por email cuando termina

- [ ] Expandir a otros reportes (ej: reporte de vacancia, reporte de distribuciones)
