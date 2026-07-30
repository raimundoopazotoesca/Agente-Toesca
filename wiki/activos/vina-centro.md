---
tipo: activo
nombre: "Viña Centro"
fondo: "TRI"
administrador: "Tres Asociados"
filas_noi: "196–214"
fuentes: 1
actualizado: 2026-07-14
---

# Viña Centro

## Datos básicos

- **Fondo**: [[fondos/ar-rentas]]
- **Administrador**: Tres Asociados
- **Filas NOI-RCSD**: 196–214

## Fuente canónica en la DB (desde 2026-07-14)

`raw_er_activo_line`, `activo_key='Viña Centro'`, vía `tools/db/ingest_er_vina.py`.
Fuente: `RAW/NOI VIÑA.xlsx` (SharePoint), no el CDG. Detalle completo del
diseño, la definición de NOI y los overrides de datos faltantes en
`wiki/db.md` → sección "Ingesta ER Viña Centro".

**Nota**: existía una ingesta previa vía `actualizar_er_vina` (dual-write
desde el ER embebido en el CDG, ver abajo) que quedó `superseded`. Pendiente
decidir si ese flujo se desactiva para que no vuelva a pisar la data.

## Fuente de datos (CDG mensual, uso: Excel entregable, no DB)

**Archivo**: `MM-AAAA INFORME EEFF VIÑA CENTRO SPA*.xlsx`
**Hoja**: "ESTADO DE RESULTADO AAAA"
**Ubicación local**: `C:\Users\raimundo.opazo\OneDrive - Toesca\Inmobiliario Toesca - Documentos\Fondo Rentas\Informes TresA\Viña Centro`
**Función**: `actualizar_er_vina`

## Estructura en CDG

- **Section 1** (filas 5–90+, cols B–CA+): datos mensuales en UF (valor = CLP / UF_mes)
  - Col B = código de cuenta, col E = valor CLP mes actual
- **Section 2** (filas 95–119+): valores estáticos sin fórmulas → requiere actualización directa _(pendiente)_
- NOI-RCSD referencia Section 2
- Fila de fechas: **fila 6** (seriales Excel)
- Fila de UF: **fila 5**

## Notas críticas

Section 2 no tiene fórmulas (a diferencia de Curicó): debe actualizarse manualmente o via `actualizar_er_vina`. Estado: _(pendiente)_.

## Vacancia (rent roll)

Fuente: `raw_rent_roll_line`, `activo_key='Viña Centro'`. Vacancia por `extra_json.tipo_arrendatario='Vacante'`.

**Regla de cálculo**: solo se considera vacancia en unidades de tipo **Locales**
(`tipo_activo_1` = Locales Comerciales/Food Court/Comercial/Walmart/Tienda
Ancla), **excluyendo Módulos y Parking** tanto del numerador como del
denominador. Ojo: filas vacantes tienen `tipo_activo_1='Vacante'` (se pierde
la categoría original) — para saber si una unidad vacante es módulo hay que
mirar el `unidad`/contexto, no confiar en `tipo_activo_1`.

Ejemplo validado periodo 2026-05: vacantes = unidad 2096 (42 m²) + unidad
3004 (81 m²) = **123 m²**; unidad M1 (7.5 m²) es un módulo → se excluye.
Denominador (locales, sin módulos/parking) = **25.227,7 m²**. Vacancia =
**0,49%**.

## Vínculos

- [[fondos/ar-rentas]]
- [[activos/mall-curico]]
- [[procesos/noi-rcsd]]
- [[conceptos/fechas-excel]]
