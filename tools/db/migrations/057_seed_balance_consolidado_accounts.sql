-- Completa el catalogo ESF usado por raw_balance_consolidado_line y factsheet.
-- La DB productiva ya puede tener estas cuentas por cargas manuales previas;
-- esta migracion hace reproducible el schema en DBs nuevas/de test.

INSERT OR IGNORE INTO dim_cuenta_eeff
    (cuenta_codigo, seccion_eeff, grupo, descripcion, es_subtotal)
VALUES
    ('ESF.efectivo', 'ESF', 'activo_corriente', 'Efectivo y equivalentes al efectivo', 0),
    ('ESF.otros_activos_corrientes', 'ESF', 'activo_corriente', 'Otros activos corrientes', 0),
    ('ESF.propiedades_inversion', 'ESF', 'activo_no_corriente', 'Propiedades de inversion', 0),
    ('ESF.otros_activos_no_corrientes', 'ESF', 'activo_no_corriente', 'Otros activos no corrientes', 0),
    ('ESF.total_activo', 'ESF', 'subtotal', 'Total activo', 1),
    ('ESF.prestamos', 'ESF', 'pasivo', 'Prestamos', 0),
    ('ESF.pasivos_impuestos_diferidos', 'ESF', 'pasivo', 'Pasivos por impuestos diferidos', 0),
    ('ESF.otros_pasivos', 'ESF', 'pasivo', 'Otros pasivos', 0),
    ('ESF.patrimonio_neto', 'ESF', 'patrimonio', 'Total patrimonio neto', 1),
    ('ESF.total_pasivo_patrimonio', 'ESF', 'subtotal', 'Total pasivo y patrimonio neto', 1);
