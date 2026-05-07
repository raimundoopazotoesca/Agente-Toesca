---
tipo: proceso
nombre: "Control de Gestión Mensual"
frecuencia: mensual
herramientas: [gestion_renta, web_bursatil, eeff, input, caja]
actualizado: 2026-05-01
---

# Flujo mensual — Control de Gestión Renta Comercial

## Pasos (mes "AAMM", ej. "2604" = abril 2026)

1. `crear_planilla_mes("2604")` → copia desde el mes anterior
2. `copiar_del_servidor(...)` → copiar al `WORK_DIR`
3. `actualizar_fecha_pendientes(...)` → B2 de hoja Pendientes = 1º día del mes
4. `obtener_precios_mes(año, mes)` → precios último día del mes del CDG
   - CDG 2604 → precios al 30/04/2026
5. `agregar_vr_bursatil_pt(...)` → [[fondos/ar-pt]] (mensual)
6. `agregar_vr_bursatil_rentas(...)` → [[fondos/ar-rentas]] series A/C/I (mensual)
   - **[[fondos/ar-apoquindo]] no tiene VR Bursátil**

## Paso 7 — Solo en fin de trimestre (mar/jun/sep/dic)

Los EEFF son del **trimestre anterior** al CDG:

| CDG mes | `leer_eeff(mes=, año=)` |
|---------|------------------------|
| marzo | `mes=12, año=año-1` |
| junio | `mes=3, año=año` |
| septiembre | `mes=6, año=año` |
| diciembre | `mes=9, año=año` |

Luego ejecutar:
- `agregar_vr_contable_pt(...)`
- `agregar_vr_contable_rentas(...)`
- `agregar_vr_contable_apoquindo(...)`

> **EEFF Viña, Curicó, INMOSA**: siempre usan el mes del CDG (no trimestre anterior)

8. `guardar_en_servidor(...)`

## Archivos involucrados

- CDG en `Control de Gestión/CDG Mensual/{YYYY}/`
- EEFF de fondos en `Fondos/Rentas TRI|Rentas PT|Rentas Apoquindo/EEFF/`
- Fuentes operativas en `Fondos/Rentas TRI/Activos/...`
- Trabajo en `WORK_DIR`

## Vínculos

- [[fondos/ar-apoquindo]] · [[fondos/ar-pt]] · [[fondos/ar-rentas]]
- [[procesos/noi-rcsd]]
- [[conceptos/ooxml]]
- [[conceptos/fechas-excel]]
