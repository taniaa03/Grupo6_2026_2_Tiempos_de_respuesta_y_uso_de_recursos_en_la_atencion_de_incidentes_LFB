/* =====================================================================
   03_poblar_modelo.sql
   Puebla las 8 dimensiones y las 2 tablas de hechos desde el staging.
   Orden de ejecución: 01_crear_modelo.sql -> carga de staging -> este script.
   Para recargar: volver a ejecutar 01 (recrea dbo; conserva stg) y luego este script.
   Reglas: README §6.3, §6.5 y diccionario del modelo (§6.10).
   ===================================================================== */
SET NOCOUNT ON;

/* ---------------- DimFecha: 365 días de 2025 + miembro 0 ---------------- */
INSERT INTO dbo.DimFecha (FechaKey, Fecha, Anio, Trimestre, Mes, Dia, DiaSemana)
VALUES (0, NULL, NULL, NULL, NULL, NULL, NULL);

WITH dias AS (
    SELECT CAST('2025-01-01' AS date) AS Fecha
    UNION ALL
    SELECT DATEADD(day, 1, Fecha) FROM dias WHERE Fecha < '2025-12-31'
)
INSERT INTO dbo.DimFecha (FechaKey, Fecha, Anio, Trimestre, Mes, Dia, DiaSemana)
SELECT YEAR(Fecha) * 10000 + MONTH(Fecha) * 100 + DAY(Fecha),
       Fecha,
       YEAR(Fecha),
       DATEPART(quarter, Fecha),
       MONTH(Fecha),
       DAY(Fecha),
       DATEDIFF(day, '19000101', Fecha) % 7 + 1      -- 01/01/1900 fue lunes: lunes=1 ... domingo=7, sin depender de DATEFIRST
FROM dias
OPTION (MAXRECURSION 400);

/* ---------------- DimHora: 0-23 -> clave 1-24 + miembro 0 ---------------- */
INSERT INTO dbo.DimHora (HoraKey, Hora, Franja) VALUES (0, NULL, N'Desconocido');

WITH horas AS (SELECT 0 AS h UNION ALL SELECT h + 1 FROM horas WHERE h < 23)
INSERT INTO dbo.DimHora (HoraKey, Hora, Franja)
SELECT h + 1, h,
       CASE WHEN h < 6  THEN N'Madrugada (0-5)'
            WHEN h < 12 THEN N'Mañana (6-11)'
            WHEN h < 18 THEN N'Tarde (12-17)'
            ELSE             N'Noche (18-23)' END
FROM horas;

/* ---------------- DimTipoIncidente ---------------- */
SET IDENTITY_INSERT dbo.DimTipoIncidente ON;
INSERT INTO dbo.DimTipoIncidente (TipoIncidenteKey, Grupo, Clasificacion, ServicioEspecial)
VALUES (0, N'Desconocido', N'Desconocido', N'Desconocido');
SET IDENTITY_INSERT dbo.DimTipoIncidente OFF;

INSERT INTO dbo.DimTipoIncidente (Grupo, Clasificacion, ServicioEspecial)
SELECT DISTINCT s.Grupo, s.Clasificacion, s.ServicioEspecial
FROM stg.Incidente s
WHERE NOT EXISTS (SELECT 1 FROM dbo.DimTipoIncidente d
                  WHERE d.Grupo = s.Grupo AND d.Clasificacion = s.Clasificacion
                    AND d.ServicioEspecial = s.ServicioEspecial)
ORDER BY s.Grupo, s.Clasificacion, s.ServicioEspecial;

/* ---------------- DimTipoPropiedad ---------------- */
SET IDENTITY_INSERT dbo.DimTipoPropiedad ON;
INSERT INTO dbo.DimTipoPropiedad (TipoPropiedadKey, Categoria, Tipo)
VALUES (0, N'Desconocido', N'Desconocido');
SET IDENTITY_INSERT dbo.DimTipoPropiedad OFF;

INSERT INTO dbo.DimTipoPropiedad (Categoria, Tipo)
SELECT DISTINCT s.Categoria, s.TipoPropiedad
FROM stg.Incidente s
WHERE NOT EXISTS (SELECT 1 FROM dbo.DimTipoPropiedad d
                  WHERE d.Categoria = s.Categoria AND d.Tipo = s.TipoPropiedad)
ORDER BY s.Categoria, s.TipoPropiedad;

/* ---------------- DimGeografia ---------------- */
SET IDENTITY_INSERT dbo.DimGeografia ON;
INSERT INTO dbo.DimGeografia (GeografiaKey, BoroughCodigo, BoroughNombre, WardCodigo, WardNombre, DistritoPostal)
VALUES (0, N'Desconocido', N'Desconocido', N'Desconocido', N'Desconocido', N'Desconocido');
SET IDENTITY_INSERT dbo.DimGeografia OFF;

INSERT INTO dbo.DimGeografia (BoroughCodigo, BoroughNombre, WardCodigo, WardNombre, DistritoPostal)
SELECT DISTINCT s.BoroughCodigo, s.BoroughNombre, s.WardCodigo, s.WardNombre, s.DistritoPostal
FROM stg.Incidente s
WHERE NOT EXISTS (SELECT 1 FROM dbo.DimGeografia d
                  WHERE d.BoroughCodigo = s.BoroughCodigo AND d.BoroughNombre = s.BoroughNombre
                    AND d.WardCodigo = s.WardCodigo AND d.WardNombre = s.WardNombre
                    AND d.DistritoPostal = s.DistritoPostal)
ORDER BY s.BoroughNombre, s.WardNombre, s.DistritoPostal;

/* ---------------- DimEstacion ---------------- */
SET IDENTITY_INSERT dbo.DimEstacion ON;
INSERT INTO dbo.DimEstacion (EstacionKey, Codigo, Nombre) VALUES (0, N'Desconocido', N'Desconocido');
SET IDENTITY_INSERT dbo.DimEstacion OFF;

INSERT INTO dbo.DimEstacion (Codigo, Nombre)
SELECT EstacionCodigo, ISNULL(MAX(EstacionNombre), N'Desconocido')
FROM stg.Movilizacion
WHERE EstacionCodigo IS NOT NULL
GROUP BY EstacionCodigo
ORDER BY EstacionCodigo;

/* ---------------- DimOrigenDespliegue (catálogo fijo) ---------------- */
INSERT INTO dbo.DimOrigenDespliegue (OrigenDespliegueKey, Origen)
VALUES (0, N'Desconocido'), (1, N'Home Station'), (2, N'Other Station');

/* ---------------- DimMotivoDemora (clave = DelayCodeId) ---------------- */
INSERT INTO dbo.DimMotivoDemora (MotivoDemoraKey, Codigo, Descripcion)
VALUES (0, N'Desconocido', N'Desconocido');

INSERT INTO dbo.DimMotivoDemora (MotivoDemoraKey, Codigo, Descripcion)
SELECT MotivoDemoraKey, MAX(DemoraCodigo), ISNULL(MAX(DemoraDescripcion), N'Desconocido')
FROM stg.Movilizacion
WHERE MotivoDemoraKey > 0
GROUP BY MotivoDemoraKey;

/* ---------------- FactIncidente ---------------- */
INSERT INTO dbo.FactIncidente (
    IncidentNumber, FechaKey, HoraKey, TipoIncidenteKey, TipoPropiedadKey, GeografiaKey,
    PrimerArriboSeg, SegundoArriboSeg, NumEstaciones, NumBombas,
    MinutosBombaRedondeados, CostoNocionalGBP, NumLlamadas, TieneMovilizacion)
SELECT s.IncidentNumber,
       ISNULL(f.FechaKey, 0),
       ISNULL(h.HoraKey, 0),
       ISNULL(ti.TipoIncidenteKey, 0),
       ISNULL(tp.TipoPropiedadKey, 0),
       ISNULL(g.GeografiaKey, 0),
       s.PrimerArriboSeg, s.SegundoArriboSeg, s.NumEstaciones, s.NumBombas,
       s.MinutosBombaRedondeados, s.CostoNocionalGBP, s.NumLlamadas, s.TieneMovilizacion
FROM stg.Incidente s
LEFT JOIN dbo.DimFecha f          ON f.Fecha = s.Fecha
LEFT JOIN dbo.DimHora h           ON h.Hora = s.Hora
LEFT JOIN dbo.DimTipoIncidente ti ON ti.Grupo = s.Grupo AND ti.Clasificacion = s.Clasificacion
                                 AND ti.ServicioEspecial = s.ServicioEspecial
LEFT JOIN dbo.DimTipoPropiedad tp ON tp.Categoria = s.Categoria AND tp.Tipo = s.TipoPropiedad
LEFT JOIN dbo.DimGeografia g      ON g.BoroughCodigo = s.BoroughCodigo AND g.BoroughNombre = s.BoroughNombre
                                 AND g.WardCodigo = s.WardCodigo AND g.WardNombre = s.WardNombre
                                 AND g.DistritoPostal = s.DistritoPostal;

/* ---------------- FactMovilizacion ----------------
   Fecha, hora, tipo de incidente, propiedad y geografía vienen del incidente
   enlazado (mismas claves que FactIncidente). Sin incidente -> claves 0.
   Estación, origen y demora vienen de la propia movilización. */
INSERT INTO dbo.FactMovilizacion (
    ResourceMobilisationId, IncidentNumber, FechaKey, HoraKey, TipoIncidenteKey,
    TipoPropiedadKey, GeografiaKey, EstacionKey, OrigenDespliegueKey, MotivoDemoraKey,
    ResourceCodigo, PerformanceReporting, FechaHoraMovilizada,
    SalidaSeg, ViajeSeg, LlegadaSeg, TieneIncidente)
SELECT m.ResourceMobilisationId,
       m.IncidentNumber,
       ISNULL(fi.FechaKey, 0),
       ISNULL(fi.HoraKey, 0),
       ISNULL(fi.TipoIncidenteKey, 0),
       ISNULL(fi.TipoPropiedadKey, 0),
       ISNULL(fi.GeografiaKey, 0),
       ISNULL(e.EstacionKey, 0),
       ISNULL(o.OrigenDespliegueKey, 0),
       ISNULL(md.MotivoDemoraKey, 0),
       m.ResourceCodigo, m.PerformanceReporting, m.FechaHoraMovilizada,
       m.SalidaSeg, m.ViajeSeg, m.LlegadaSeg,
       CASE WHEN fi.IncidentNumber IS NULL THEN 0 ELSE 1 END
FROM stg.Movilizacion m
LEFT JOIN dbo.FactIncidente fi       ON fi.IncidentNumber = m.IncidentNumber
LEFT JOIN dbo.DimEstacion e          ON e.Codigo = m.EstacionCodigo
LEFT JOIN dbo.DimOrigenDespliegue o  ON o.OrigenDespliegueKey = m.OrigenDespliegueKey
LEFT JOIN dbo.DimMotivoDemora md     ON md.MotivoDemoraKey = m.MotivoDemoraKey;

PRINT 'Dimensiones y hechos poblados.';
