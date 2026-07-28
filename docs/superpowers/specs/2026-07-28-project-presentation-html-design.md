# Presentación ejecutiva interactiva del proyecto — Diseño

**Fecha:** 2026-07-28  
**Estado:** aprobado en brainstorming  
**Audiencia:** directorio y comité ejecutivo  
**Duración objetivo:** 10–15 minutos, incluyendo una demostración en vivo  

## Objetivo

Mostrar de forma clara y convincente el trabajo realizado en el proyecto
Automation Agent Toesca, demostrar que ya existen productos funcionales y
explicar el roadmap como la continuación lógica del avance alcanzado.

El énfasis principal es evidenciar progreso. La solicitud de apoyo y recursos
para continuar el roadmap es secundaria y se presenta mediante decisiones
ejecutivas concretas, no como un discurso comercial separado.

## Dirección narrativa

La presentación sigue la secuencia **avance → evidencia → demostración →
roadmap → decisiones**.

La tesis central es:

> El proyecto dejó de ser un conjunto de automatizaciones sobre planillas y se
> está convirtiendo en una plataforma de inteligencia financiera con una sola
> fuente de información, controles verificables y productos concretos.

La demostración en vivo funciona como prueba dentro de esa historia. No es un
anexo técnico.

## Estructura

La presentación tendrá 13 pantallas:

1. **Portada** — transformación desde automatización hacia inteligencia
   financiera.
2. **Tesis ejecutiva** — el valor de una sola fuente confiable.
3. **Evolución** — hitos del proyecto entre abril y julio de 2026.
4. **Portfolio** — cobertura de TRI, PT y Apo, incluyendo el look-through y la
   exclusión vigente de Machalí.
5. **Arquitectura** — fuentes originales → ingesta validada → SQLite canónico →
   KPIs → outputs.
6. **Evidencia cuantitativa** — cobertura, integridad y volumen procesado.
7. **Productos funcionando** — factsheet, centro de ingesta y asistente.
8. **Confianza y control** — validación humana, trazabilidad, idempotencia,
   seguridad y consultas de solo lectura.
9. **Fase 0 completada** — principales logros y criterio de salida.
10. **Fase 1** — próximos entregables de la plataforma determinística.
11. **Horizonte F2–F4** — asistente fortalecido, conocimiento organizacional y
    copilot.
12. **Decisiones ejecutivas** — apoyos y definiciones necesarios para sostener
    el avance.
13. **Cierre** — norte estratégico y secuencia de valor.

La pantalla 7 será la pausa explícita para realizar la demostración en vivo en
este orden:

1. factsheet;
2. centro de ingesta;
3. asistente.

La presentación no abrirá ni controlará esas aplicaciones. Se asume que estarán
abiertas previamente en pestañas separadas. Así se evitan enlaces locales
frágiles y la presentación sigue siendo utilizable si una demo no está
disponible.

## Sistema visual

La dirección visual será editorial, sobria y ejecutiva:

- fondo azul petróleo oscuro;
- marfil cálido para texto principal;
- verde menta para progreso, resultados y estados completados;
- ámbar para decisiones, riesgos o asuntos que requieren atención;
- titulares con serif editorial;
- navegación, etiquetas y datos con sans-serif de alta legibilidad;
- grilla tenue, bordes finos y formas CSS como recursos gráficos;
- cifras grandes y pocas ideas por pantalla.

No se usarán imágenes decorativas, emojis como iconos ni ilustraciones
generadas. La identidad visual se apoya en tipografía, color, composición,
diagramas y datos verificables.

## Interacciones

La presentación se comportará como un deck de pantalla completa:

- navegación con flechas, espacio, Page Up/Page Down, Home y End;
- controles anterior/siguiente visibles;
- índice lateral y contador de pantalla;
- barra de progreso;
- gestos verticales en dispositivos táctiles;
- tabs interactivos para arquitectura, productos y fases del roadmap;
- botón para imprimir o guardar como PDF;
- foco visible y etiquetas accesibles;
- respeto por `prefers-reduced-motion`.

Las tabs permiten profundizar sin aumentar el número de pantallas. La primera
vista de cada tab debe comunicar la idea principal aunque el expositor no
interactúe.

## Arquitectura técnica

El entregable será una única aplicación web de una ruta, construida dentro de
`project-presentation/` con la estructura de Sites ya existente.

Componentes lógicos:

1. **Modelo de contenido estático** — metadatos de pantallas, arquitectura,
   productos y fases.
2. **Controlador del deck** — estado de pantalla activa, navegación por teclado
   y touch.
3. **Componentes interactivos** — tabs para arquitectura, superficies y
   roadmap.
4. **Sistema visual** — variables, layouts responsive, transiciones y estilos
   de impresión.
5. **Metadatos del sitio** — título y descripción específicos del proyecto.

No habrá persistencia, autenticación, APIs, carga dinámica ni conexión a la DB
durante la exposición. El HTML publicado representa una fotografía del estado
del proyecto al 2026-07-28.

## Fuente y verificación del contenido

Las fuentes canónicas para preparar el contenido son:

- `ROADMAP.md`, versión vigente;
- `CODEX.md`;
- entradas recientes de `wiki/log.md`;
- consultas de solo lectura sobre `memory/agente_toesca_v2.db`;
- código productivo cuando sea necesario verificar una capacidad.

Cada cifra expuesta debe cumplir una de estas condiciones:

- provenir de una consulta ejecutada contra la DB;
- estar registrada como resultado verificado en el roadmap o log;
- describir una capacidad demostrable en el código actual.

Los estados del roadmap se mostrarán sin falsa precisión. F0 se presenta como
completada; F1 como fase activa; F2–F4 como horizonte condicionado por criterios
de salida.

## Manejo de fallos

La presentación no depende de servicios en tiempo de ejecución. Si el
factsheet, la ingesta o el asistente no están disponibles durante la reunión,
la pantalla de productos conserva una explicación suficiente para continuar la
exposición.

La navegación limita siempre el índice al rango de pantallas válido. Las
interacciones no deben cambiar el layout ni ocultar información imprescindible.

## Responsive y accesibilidad

La experiencia principal se optimiza para proyector y notebook en formato
horizontal. También debe:

- conservar navegación y contenido legible en tablet y móvil;
- evitar scroll horizontal;
- usar objetivos táctiles de al menos 44 × 44 px;
- mantener contraste mínimo de 4,5:1 para texto normal;
- ofrecer estados de foco visibles;
- mantener orden semántico y de tabulación;
- imprimir cada pantalla como una página apaisada.

## Verificación

Antes de publicar:

1. ejecutar el build de producción;
2. ejecutar los tests de contenido y navegación existentes o actualizados;
3. comprobar que las 13 pantallas se renderizan;
4. verificar navegación por teclado, límites y tabs;
5. revisar que las cifras visibles coincidan con sus fuentes;
6. revisar responsive en 375, 768, 1024 y 1440 px;
7. verificar estilos de impresión y movimiento reducido;
8. confirmar que no queden metadatos ni elementos del starter.

## Fuera de alcance

- conectar la presentación a la DB en tiempo real;
- controlar las aplicaciones de la demostración;
- incorporar información confidencial de detalle;
- crear una nueva presentación mensual como producto de la plataforma;
- reemplazar o modificar factsheet, ingesta o asistente;
- agregar backend, autenticación o persistencia.

