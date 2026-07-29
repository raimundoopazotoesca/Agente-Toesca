# Navegación sincronizada del detalle de ingesta

**Fecha:** 2026-07-29
**Estado:** Aprobado

## Contexto

Las tarjetas de la pantalla inicial de ingesta muestran una línea de tiempo resumida y,
cuando existen sub-ingestas, una matriz colapsable con el detalle por proveedor o fondo.
La línea de tiempo superior se navega con flechas, pero la matriz inferior conserva sus
períodos iniciales y puede mostrar una barra de desplazamiento horizontal. Esa barra
también desplaza fuera de la vista la columna que identifica cada fila.

## Objetivo

Usar las flechas de la línea de tiempo superior como único control de navegación temporal
de la tarjeta. Cada cambio de período debe actualizar simultáneamente el resumen y la
matriz de detalle, manteniendo siempre visible la columna con los nombres de proveedores
o fondos.

## Enfoques evaluados

1. **Re-render sincronizado desde el cache existente (elegido).** Al navegar, recortar la
   misma ventana del rango precargado tanto para la línea de tiempo como para cada
   sub-ingesta. Elimina el scroll inferior y mantiene una única fuente de estado.
2. **Sincronizar dos scrolls horizontales.** Mantendría la matriz ancha y movería ambos
   contenedores por píxeles. Agrega complejidad, conserva un control redundante y puede
   desalinearse con tamaños responsivos.
3. **Fijar la primera columna con CSS `position: sticky`.** Mantendría visible la leyenda,
   pero no resuelve la duplicación de navegación ni garantiza que resumen y detalle
   muestren los mismos períodos.

## Diseño

- El `offset` de cada tarjeta continúa siendo el estado único de navegación.
- `navegarTimeline` obtiene del cache la ventana correspondiente al nuevo `offset`.
- La línea de tiempo superior se vuelve a renderizar con esa ventana.
- Si la tarjeta tiene detalle, cada fila se vuelve a renderizar usando los períodos de su
  propia serie dentro del mismo rango y offset.
- Los encabezados de la matriz usan exactamente los mismos períodos visibles que la línea
  de tiempo superior.
- La columna de nombres permanece fija en la primera columna de la matriz.
- Se elimina `overflow-x: auto` del cuerpo expandido; la matriz ocupa el ancho disponible
  de la tarjeta y distribuye sus columnas sin provocar scroll horizontal.
- Los botones anterior/siguiente conservan sus límites actuales y estados deshabilitados.
- Las celdas pendientes regeneradas continúan siendo clickeables y abren la ingesta para
  el proveedor/fondo y período seleccionados.

## Backend y datos

No se modifica el backend. `GET /api/estado_ingesta/timeline_range` ya devuelve:

- el rango completo navegable;
- la cantidad de períodos visibles;
- las series de cada sub-ingesta.

El frontend reutiliza ese payload y el cache existente.

## Pruebas

- Una prueba de regresión debe demostrar que al cambiar el offset se actualizan tanto la
  línea superior como los encabezados y celdas del detalle.
- Debe verificarse que las celdas pendientes regeneradas conservan su navegación.
- Debe verificarse que el detalle no tenga scrollbar horizontal en los anchos de tarjeta
  usados por la grilla.
- Se ejecutarán los tests relacionados con estado de ingesta y una validación visual de
  las tarjetas abiertas.

## Fuera de alcance

- Cambiar el rango histórico disponible.
- Modificar la frecuencia o la lógica de períodos esperados.
- Rediseñar las tarjetas o la paleta de estados.
- Cambiar endpoints o consultas a la base de datos.
