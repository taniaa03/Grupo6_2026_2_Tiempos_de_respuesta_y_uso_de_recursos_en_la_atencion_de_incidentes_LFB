/* =====================================================================
   04_validaciones.sql
   Controles de calidad después de poblar el modelo.
   Comparar los conteos con data/resumen_calidad_etl.json.
   ===================================================================== */

-- 1. Filas por tabla
SELECT 'DimFecha' AS tabla, COUNT(*) AS filas FROM dbo.DimFecha
UNION ALL SELECT 'DimHora', COUNT(*) FROM dbo.DimHora
UNION ALL SELECT 'DimTipoIncidente', COUNT(*) FROM dbo.DimTipoIncidente
UNION ALL SELECT 'DimTipoPropiedad', COUNT(*) FROM dbo.DimTipoPropiedad
UNION ALL SELECT 'DimGeografia', COUNT(*) FROM dbo.DimGeografia
UNION ALL SELECT 'DimEstacion', COUNT(*) FROM dbo.DimEstacion
UNION ALL SELECT 'DimOrigenDespliegue', COUNT(*) FROM dbo.DimOrigenDespliegue
UNION ALL SELECT 'DimMotivoDemora', COUNT(*) FROM dbo.DimMotivoDemora
UNION ALL SELECT 'FactIncidente', COUNT(*) FROM dbo.FactIncidente
UNION ALL SELECT 'FactMovilizacion', COUNT(*) FROM dbo.FactMovilizacion;
-- Esperado: DimFecha 366, DimHora 25, DimOrigenDespliegue 3,
--           FactIncidente = stg.Incidente, FactMovilizacion = stg.Movilizacion.

-- 2. Ninguna fila se perdió entre staging y hechos (solo válido antes de vaciar el staging)
SELECT (SELECT COUNT(*) FROM stg.Incidente)    - (SELECT COUNT(*) FROM dbo.FactIncidente)    AS dif_incidentes,
       (SELECT COUNT(*) FROM stg.Movilizacion) - (SELECT COUNT(*) FROM dbo.FactMovilizacion) AS dif_movilizaciones;
-- Esperado: 0 y 0.

-- 3. Uso del miembro desconocido (clave 0) por dimensión
SELECT 'FI.Fecha' AS clave, SUM(CASE WHEN FechaKey = 0 THEN 1 ELSE 0 END) AS filas_con_0 FROM dbo.FactIncidente
UNION ALL SELECT 'FI.Hora', SUM(CASE WHEN HoraKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactIncidente
UNION ALL SELECT 'FI.TipoIncidente', SUM(CASE WHEN TipoIncidenteKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactIncidente
UNION ALL SELECT 'FI.TipoPropiedad', SUM(CASE WHEN TipoPropiedadKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactIncidente
UNION ALL SELECT 'FI.Geografia', SUM(CASE WHEN GeografiaKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactIncidente
UNION ALL SELECT 'FM.Estacion', SUM(CASE WHEN EstacionKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactMovilizacion
UNION ALL SELECT 'FM.Origen', SUM(CASE WHEN OrigenDespliegueKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactMovilizacion
UNION ALL SELECT 'FM.MotivoDemora', SUM(CASE WHEN MotivoDemoraKey = 0 THEN 1 ELSE 0 END) FROM dbo.FactMovilizacion
UNION ALL SELECT 'FM.SinIncidente', SUM(CASE WHEN TieneIncidente = 0 THEN 1 ELSE 0 END) FROM dbo.FactMovilizacion;

-- 4. Enlace entre hechos
SELECT TieneMovilizacion, COUNT(*) AS incidentes FROM dbo.FactIncidente GROUP BY TieneMovilizacion;
SELECT TieneIncidente, COUNT(*) AS movilizaciones FROM dbo.FactMovilizacion GROUP BY TieneIncidente;

-- 5. Jerarquía borough -> ward: wards asignados a más de un borough
SELECT WardCodigo, COUNT(DISTINCT BoroughCodigo) AS boroughs
FROM dbo.DimGeografia
WHERE WardCodigo <> N'Desconocido'
GROUP BY WardCodigo
HAVING COUNT(DISTINCT BoroughCodigo) > 1;

-- 6. Coherencia de tiempos: llegada = salida + viaje (diferencias de pocos segundos son de la fuente)
SELECT COUNT(*) AS movilizaciones_comparables,
       SUM(CASE WHEN ABS(LlegadaSeg - (SalidaSeg + ViajeSeg)) > 1 THEN 1 ELSE 0 END) AS con_diferencia
FROM dbo.FactMovilizacion
WHERE SalidaSeg IS NOT NULL AND ViajeSeg IS NOT NULL AND LlegadaSeg IS NOT NULL;

-- 7. Resumen de control por grupo de incidente
SELECT t.Grupo,
       COUNT(*)                                 AS incidentes,
       AVG(CAST(f.PrimerArriboSeg AS float))    AS prom_primer_arribo_seg,
       SUM(f.NumBombas)                         AS participaciones_bombas,
       SUM(f.CostoNocionalGBP)                  AS costo_nocional_gbp
FROM dbo.FactIncidente f
JOIN dbo.DimTipoIncidente t ON t.TipoIncidenteKey = f.TipoIncidenteKey
GROUP BY t.Grupo
ORDER BY incidentes DESC;
