---
tipo: activo
nombre: "Viña Centro"
fondo: "A&R Rentas"
administrador: "Tres Asociados"
filas_noi: "196–214"
fuentes: 0
actualizado: 2026-05-01
---

# Viña Centro

## Datos básicos

- **Fondo**: [[fondos/ar-rentas]]
- **Administrador**: Tres Asociados
- **Filas NOI-RCSD**: 196–214

## Fuente de datos

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

## Vínculos

- [[fondos/ar-rentas]]
- [[activos/mall-curico]]
- [[procesos/noi-rcsd]]
- [[conceptos/fechas-excel]]
