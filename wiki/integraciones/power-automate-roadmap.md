# Power Automate — Roadmap de Implementación

## Resumen por fases

| Fase | Qué | Requiere | Tiempo estimado |
|---|---|---|---|
| **1** | Flujos PA puros — email → SharePoint + notificación | Solo PA web | 2-3 horas |
| **2** | Recordatorios programados | Solo PA web | 30 min |
| **3** | Conectividad PA ↔ agente local | ngrok o gateway | 1 hora |
| **4** | Flujos completos PA → agente → resultado | Fase 3 completa | 2-3 horas |

---

## Fase 1 — Email → SharePoint + Notificación (sin conectividad)

**Objetivo:** cuando llega email de remitente conocido con adjunto, PA guarda el archivo en SharePoint y avisa.
El usuario solo tiene que decirle al agente que procese — el archivo ya está disponible.

### Flujo 1A — Remitentes externos (Nicole / Valentina / Leonardo)

**Cuándo crear:** hacer uno por cada remitente o un solo flujo con condición.

**En make.powerautomate.com:**

```
1. Nuevo flujo → Automatizado → "When a new email arrives (V3)" [Outlook]
   - Carpeta: Inbox
   - Solo con adjuntos: Sí
   - Remitente: nicole.carvajal@jll.com  (repetir para los otros)

2. Condición: ¿el asunto contiene "Rent Roll" O "NOI"?
   → Sí: continuar
   → No: terminar

3. "Apply to each" sobre Attachments

4. Acción: "Create file" [SharePoint]
   - Site: Inmobiliario Toesca
   - Folder: /Fondo Rentas/JLL/Recibidos/
   - File name: @{triggerOutputs()?['body/receivedDateTime']}_@{item()?['name']}
   - File content: @{item()?['contentBytes']}

5. Acción: "Post a message in a chat or channel" [Teams]
   - Canal: General (o chat personal)
   - Mensaje: "📎 Llegó @{item()?['name']} de Nicole Carvajal. Guardado en SharePoint/JLL/Recibidos"
```

**Remitentes y carpetas destino:**
| Remitente | Email | Carpeta SharePoint |
|---|---|---|
| Nicole Carvajal (JLL) | nicole.carvajal@jll.com | `/Fondo Rentas/JLL/Recibidos/` |
| Valentina Bravo (TresA) | valentina.bravo@tresasociados.cl | `/Fondo Rentas/TresA/Recibidos/` |
| Leonardo Cantillana (Araucana) | [confirmar email] | `/Fondo Rentas/INMOSA/Recibidos/` |

### Flujo 1B — Saldo Caja (María José Castro, lunes)

```
Trigger: "When a new email arrives (V3)"
   - Remitente: maria.jose@toesca.cl (confirmar email)
   - Solo con adjuntos: Sí

Apply to each → Attachments:
   Filtro: nombre contiene "Saldo Caja" O "FFMM"

   "Create file" [SharePoint]
   - Folder: /Controles de Gestión/Saldo Caja/Recibidos/
   - File name: @{item()?['name']}

   "Post message" [Teams]:
   "💰 Saldo Caja recibido: @{item()?['name']}. Guardado en SharePoint."
```

**Prerequisito:** confirmar emails exactos de Valentina, Leonardo y María José.

---

## Fase 2 — Recordatorios programados (sin conectividad)

### Flujo 2A — Recordatorio mensual CDG (día 10)

```
Trigger: Recurrence
   - Intervalo: 1 mes
   - Día del mes: 10
   - Hora: 09:00

Acción: "Post message" [Teams] o "Send an email" [Outlook]
   Mensaje:
   "📋 CDG Mensual — verificar archivos disponibles:
   □ RR JLL (Nicole)
   □ EEFF Viña Centro (Valentina)
   □ EEFF Curicó (Valentina)
   □ ER-FC INMOSA (Leonardo)
   □ Saldo Caja (María José)
   Si faltan, llamar al agente: 'enviar_correos_solicitud_cdg {AAMM} {año}'"
```

### Flujo 2B — Alerta trimestral factsheets (enero/abril/julio/octubre)

```
Trigger: Recurrence
   - Intervalo: 3 meses
   - Inicio: 2026-04-01T09:00:00

Acción: "Post message" [Teams]
   "📊 Trimestre cerrado — pendiente:
   □ EEFF de los 3 fondos en SharePoint
   □ Actualizar Input sheets (balance, fechas)
   □ Generar factsheets PT / APO / TRI"
```

---

## Fase 3 — Conectividad PA ↔ agente local

**Objetivo:** PA puede llamar al agente en tu laptop vía HTTP.

### Opción A: ngrok (recomendada para probar rápido)

```powershell
# 1. Instalar ngrok
winget install ngrok

# 2. Registrarse en ngrok.com → obtener authtoken

# 3. Configurar token
ngrok config add-authtoken <tu-token>

# 4. Iniciar agente
python agent.py --server

# 5. En otra terminal, exponer el puerto
ngrok http 5000
# → Genera URL pública: https://abc123.ngrok-free.app
```

Limitación: la URL cambia cada vez que reinicias ngrok (plan gratis). Para URL fija: plan ngrok Pro (~$8/mes) o usar Opción B.

### Opción B: On-premises data gateway (Microsoft, gratis)

1. Descargar desde: `aka.ms/on-premises-data-gateway`
2. Instalar en la laptop, loguearse con cuenta Microsoft 365
3. En PA: Datos → Gateways → seleccionar el gateway instalado
4. PA puede llamar a recursos locales vía el gateway

Esta opción es más estable pero más compleja de configurar.

---

## Fase 4 — PA → Agente (requiere Fase 3)

### Flujo 4A — Email → agente procesa automáticamente

```
Trigger: "When a new email arrives (V3)" [Nicole Carvajal]

Apply to each → Attachments:
   "Create file" [SharePoint] → guarda en /JLL/Recibidos/

Acción: "HTTP" [conector HTTP]
   - Método: POST
   - URI: https://<tu-url-ngrok>/run
   - Headers: Content-Type: application/json
   - Body: {"instruction": "Se recibió RR JLL, el archivo está en SharePoint/JLL/Recibidos/@{item()?['name']}. Actualizar NOI PT y Apoquindo."}

Acción: "Post message" [Teams]
   "✅ RR JLL procesado por el agente."
```

### Flujo 4B — Verificación CDG + solicitud de archivos faltantes (día 10)

```
Trigger: Recurrence día 10

Acción: "HTTP" POST /run
   Body: {"instruction": "verificar_archivos_cdg 2605 2026"}

Condición: response.body.response contiene "[FALTA]"
   → Sí: POST /run {"instruction": "enviar_correos_solicitud_cdg 2605 2026"}
   → Post Teams: "CDG: se enviaron solicitudes de archivos faltantes"
   → No: Post Teams: "CDG: todos los archivos están disponibles ✅"
```

---

## Orden de implementación recomendado

1. **Hoy:** Crear Flujo 1B (Saldo Caja) — más fácil, impacto inmediato los lunes
2. **Esta semana:** Crear Flujos 1A (Nicole / Valentina / Leonardo) + confirmar emails
3. **Esta semana:** Crear Flujos 2A y 2B (recordatorios) — 30 minutos total
4. **Próxima semana:** Instalar ngrok o gateway (Fase 3)
5. **Después:** Flujos 4A y 4B

---

## Información pendiente de confirmar

| Dato | Estado |
|---|---|
| Email de Valentina Bravo (TresA) | ❓ confirmar |
| Email de Leonardo Cantillana (Araucana) | ❓ confirmar |
| Email de María José Castro | ❓ confirmar |
| ¿Tienes Teams en la empresa? | ❓ confirmar |
| ¿Prefieres notificación Teams o email? | ❓ confirmar |
