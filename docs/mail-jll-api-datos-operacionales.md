# Mail a JLL — Solicitud API datos operacionales Parque Titanium

**Fecha**: 2026-07-07
**Para**: [contactos JLL — Nicole Carvajal, equipo de sistemas]
**Asunto**: Alianza API JLL — detalle de información y consultas pendientes (Parque Titanium)

---

Estimados,

Retomando lo conversado en la reunión respecto a la alianza para acceder vía API a la base de datos de JLL, les envío detallado el listado de información que necesitamos y algunas consultas que nos ayudarían a cerrar el alcance antes de que ustedes definan la especificación técnica.

El objetivo por nuestro lado es reconstruir de forma sistemática y automatizada toda la información operacional histórica de los activos que ustedes administran, partiendo por **Parque Titanium (Torre A S.A. + Inmobiliaria Boulevard PT SpA)**, con ventana desde el **inicio del fondo (noviembre 2017)** hasta la fecha, en frecuencia mensual.

## 1. Información que necesitamos vía API

Idealmente estructurada en cuatro endpoints:

### 1.1 Rent Roll — snapshot mensual

Un registro por unidad (ocupada o vacante), con corte al último día de cada mes. Campos requeridos:

- Activo (Torre A / Boulevard PT)
- Tipo de unidad (Oficina / Local Comercial / Bodega / Estacionamiento)
- ID estable de unidad (piso/número)
- ID estable de contrato (que se mantenga a través de renovaciones)
- Arrendatario (razón social)
- Rubro del arrendatario (Banco, Deporte, Padel, Seguros, Construcción, Otro, etc.)
- m² útiles
- Estado (ocupada / vacante / gracia / descuento)
- Renta base UF/mes
- Gracia UF/mes (si aplica)
- Descuento UF/mes (si aplica)
- Fecha de inicio de contrato
- Fecha de término de contrato
- Fecha de corte del snapshot

### 1.2 Estado de Resultado mensual por activo

Ingresos y gastos operacionales desagregados por cuenta, en CLP y UF, valor UF del mes utilizado.

- Ingresos: arriendo base, gastos comunes recuperados, otros
- Gastos operacionales: gastos comunes no recuperados, mantención, comisiones, seguros, contribuciones, servicios básicos, otros
- NOI mensual

### 1.3 Facturación mensual por contrato / arrendatario (crítico)

Este endpoint es el que nos permite clasificar los ingresos por rubro, arrendatario, tipo de unidad y segmento del activo. Sin él perdemos toda la trazabilidad ingreso → arrendatario. Un registro por contrato-mes con:

- ID contrato (mismo que rent roll)
- ID unidad (mismo que rent roll)
- Activo, arrendatario, rubro (redundantes con rent roll pero facilitan queries)
- Periodo (YYYY-MM)
- Facturación por concepto en UF: arriendo base, gastos comunes, reajuste UF, penalizaciones, servicios, otros
- Facturación total UF del contrato en el mes

### 1.4 Cobranza / recaudación mensual

Idealmente **por contrato** (mismo ID que rent roll y facturación), y también agregado por activo:

- Facturación UF
- Recaudación UF
- Recaudación con plan de pago UF
- Morosidad por tramos de días: 0-30, 30-60, 60-90, >90

> Nota: parking queda fuera del alcance de la API JLL — lo manejamos directamente con Saba.
> Nota: contribuciones y seguros también quedan fuera — los administramos internamente vía fórmulas asociadas a la UF.

**Formato solicitado**: respuesta en JSON, con histórico disponible desde nov-2017 y actualización mensual. En cuanto a autenticación, nos acomoda lo que les resulte más simple de implementar de su lado (API key es suficiente para nuestro caso). Si algún endpoint devuelve volúmenes grandes de datos, agradecemos que venga paginado.

## 2. Consultas para cerrar alcance

Antes de que definan la spec técnica, nos ayudaría mucho poder resolver los siguientes puntos:

1. **Cobertura histórica del sistema**: ¿la base de datos JLL contiene información desde noviembre 2017 (inicio del fondo) o hay una fecha de corte anterior a la cual no hay registros digitales? En caso de haber un corte, ¿cuál es?

2. **Morosidad por tramos**: ¿el sistema tiene la morosidad segmentada por antigüedad (0-30, 30-60, 60-90, >90) o solo el total? El fact sheet reporta morosidad promedio >30 días.

3. **ID estable de contrato y unidad**: crítico para poder rastrear renovaciones, cambios de arrendatario y modificaciones a lo largo del tiempo. ¿Existe un identificador único por contrato que se mantenga entre renovaciones, o cada renovación genera un ID nuevo? Lo mismo para unidades.

4. **Gracia y descuento**: en el rent roll, ¿estos figuran como campos separados con montos explícitos, o están embebidos en la renta efectiva del mes? Necesitamos poder separarlos para reportar "renta en gracia" y "renta en descuento" como líneas independientes.

5. **Motivo de vacancia**: ¿el sistema registra el motivo por el que una unidad está vacante (nunca arrendada, salida reciente, en remodelación, en negociación)? Esto ayuda a calcular absorción neta correctamente.

6. **Clasificación de rubro del arrendatario**: ¿es un campo estructurado (enum controlado) o texto libre? Si es libre, ¿qué convención usan para categorías tipo "Banco", "Deporte", "Padel", "Seguros", etc.?

7. **Tipo de unidad**: ¿"Oficina / Local Comercial / Bodega / Estacionamiento" viene como campo estructurado o hay que inferirlo desde el nombre/código de la unidad?

8. **Cuentas del ER**: ¿existe un plan de cuentas estándar que ustedes usan para todos los activos administrados, o el plan varía por activo? Ideal contar con el mapeo de códigos-descripción para poder normalizar. Tenemos claro que contribuciones y seguros no vienen en su reporte (los administramos nosotros); confirmar si hay otros conceptos también excluidos.

9. **Cruce ingreso ↔ contrato**: en su sistema, ¿los ingresos del ER se pueden trazar de vuelta al contrato/arrendatario que los generó, o el ER es puramente contable sin ese link? Este cruce es el que nos permite clasificar ingresos por rubro, arrendatario y tipo de unidad. Si no está expuesto hoy, ¿sería viable incluirlo en la API?

10. **Cobranza a nivel contrato**: ¿la morosidad y recaudación las pueden desglosar por contrato (mismo ID que el rent roll) o solo agregado por activo?

11. **Refresco de la API**: ¿con qué frecuencia se actualizarían los datos disponibles vía API? (diaria, semanal, mensual al cierre). ¿Existiría algún periodo de "cierre en curso" donde el mes recién cerrado aún no esté disponible?

12. **Historicidad del rent roll**: ¿el sistema conserva versiones históricas del rent roll (snapshot cada fin de mes) o solo el estado actual? Si es solo actual, ¿qué tanto podríamos reconstruir hacia atrás desde ustedes?

13. **Trazabilidad de cambios contractuales**: renovaciones, salidas anticipadas, ampliaciones de superficie arrendada dentro del mismo contrato. ¿Cómo se representan?

14. **Anexos operacionales que no están en el rent roll estándar**: ¿tienen registro de eventos como remodelaciones, tiempos de reconstrucción de locales, gastos extraordinarios asociados a cambios de arrendatario? Nos sirven para explicar quiebres en NOI.

15. **Ambiente de pruebas**: ¿nos podrían habilitar un ambiente sandbox / staging para hacer las primeras integraciones antes de conectarnos a producción?

16. **Documentación**: ¿la API vendría con documentación OpenAPI/Swagger o similar? Nos permitiría automatizar la generación de clientes.

## 3. Próximos pasos propuestos

Una vez tengamos claridad sobre los puntos anteriores, podemos:

1. Cerrar la especificación técnica de los endpoints en conjunto con su equipo.
2. Definir el mecanismo de autenticación y las credenciales de acceso.
3. Coordinar una primera carga histórica de prueba con un activo (proponemos Torre A) para validar el pipeline end-to-end.
4. Escalar al resto de los activos administrados por JLL una vez validado.

Mientras tanto, seguimos operando con los Rent Roll Excel que ustedes nos envían mensualmente. Si pudieran adicionalmente compartirnos el histórico completo de RR desde nov-2017 (en el formato actual `{AAMM} Rent Roll y NOI.xlsx`) para lo que aún no tenemos consolidado, avanzamos en paralelo con la ingesta histórica.

Cualquier duda quedo atento.

Saludos,
Raimundo Opazo
Toesca AGF
