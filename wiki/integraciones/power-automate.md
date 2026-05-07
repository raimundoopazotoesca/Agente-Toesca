# Power Automate — Integración con el Agente

## Cómo conectar PA al agente

El agente expone un servidor HTTP Flask cuando se inicia con `--server`:

```bash
python agent.py --server         # puerto 5000 (default)
python agent.py --server 8080    # puerto alternativo
```

**Endpoints:**
- `POST /run` — body JSON: `{"instruction": "texto en español"}`
- `GET /health` — verifica que el servidor esté vivo

**Desde Power Automate:** usar el conector **HTTP** con:
- Método: POST
- URI: `http://localhost:5000/run` (o la IP/ngrok del equipo)
- Headers: `Content-Type: application/json`
- Body: `{"instruction": "verificar_archivos_cdg 2605 2026"}`

---

## Flujos recomendados

### 1. Monitor emails con adjuntos (prioridad alta)

| Campo | Valor |
|---|---|
| Trigger | "When a new email arrives (V3)" — Outlook |
| Filtro | From = remitente conocido, HasAttachment = true |
| Acción 1 | "Create file" — SharePoint — guardar adjunto en carpeta según remitente |
| Acción 2 | HTTP POST `/run` con instruction dinámica |
| Acción 3 | Notificación Teams |

**Remitentes conocidos:**
| Remitente | Archivo | Instrucción al agente |
|---|---|---|
| Nicole Carvajal (JLL) | `{AAMM} Rent Roll y NOI.xlsx` | `"Se recibió RR JLL {mes}, actualizar NOI"` |
| Valentina Bravo (TresA) | EEFF Viña Centro / Curicó | `"Se recibió EEFF {activo}, procesar"` |
| Leonardo Cantillana (Araucana) | ER-FC INMOSA | `"Se recibió INMOSA {mes}, actualizar NOI INMOSA"` |
| María José Castro | Saldo Caja | `"Se recibió Saldo Caja {fecha}, copiar_datos_saldo_caja"` |

### 2. Verificación mensual CDG (día 10 de cada mes)

```
Trigger: Recurrence — día 10, hora 09:00
→ POST /run: "verificar_archivos_cdg {AAMM} {año}"
→ Si hay faltantes: POST /run: "enviar_correos_solicitud_cdg {AAMM} {año}"
→ Notificación Teams con resultado
```

### 3. Rutina Saldo Caja — lunes

```
Trigger: "When a new email arrives" FROM maria.jose.castro@toesca.cl
→ POST /run: "copiar_datos_saldo_caja desde el adjunto recibido hoy"
→ Notificación
```

### 4. Alerta trimestral factsheets

```
Trigger: Recurrence — 1er lunes de enero/abril/julio/octubre
→ Notificación Teams: "Trimestre cerrado — pendiente factsheets"
→ Opcional: POST /run: "buscar EEFF disponibles en SharePoint para trimestre {T}"
```

---

## Framework: ¿cuándo agrega valor PA en una nueva funcionalidad?

Aplicar este criterio cuando el agente aprenda algo nuevo:

| Pregunta | Sí → PA agrega valor |
|---|---|
| ¿Hay trigger externo predecible? | Email de remitente conocido, fecha fija, archivo en carpeta |
| ¿El paso humano es solo detectar + rutear? | Bajar archivo y llamar al agente |
| ¿La tarea es periódica y olvidable? | Mensual, trimestral, semanal |
| ¿Es un chequeo de estado? | "¿llegaron todos los archivos?" |
| ¿La lógica condicional es simple? | "si X entonces Y, si no Z" |

**No agregar PA cuando:**
- La tarea requiere razonamiento complejo (el LLM lo hace mejor)
- La tarea es ad-hoc sin patrón predecible
- El volumen es tan bajo que el overhead no vale

---

## Limitaciones conocidas

- El servidor Flask corre localmente — PA necesita acceso de red (ngrok, Azure, o gateway on-premises del mismo tenant)
- Las fórmulas Caja (R5, R22, R26) requieren abrir Excel manualmente para recalcular — PA no resuelve esto
- `run_agent()` es sincrónico — PA debe usar timeout largo (~5 min) para tareas pesadas
