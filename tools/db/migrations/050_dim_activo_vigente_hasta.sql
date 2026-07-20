-- Agrega vigente_hasta a dim_activo para activos divestidos (ej. Strip Machalí,
-- vendido sept-2025). NULL = activo vigente. Un periodo (YYYY-MM) = último mes
-- en que el activo contribuye a consolidaciones de fondo; después de ese
-- periodo se excluye sin bloquear la ventana de otros activos vigentes.
ALTER TABLE dim_activo ADD COLUMN vigente_hasta TEXT;
