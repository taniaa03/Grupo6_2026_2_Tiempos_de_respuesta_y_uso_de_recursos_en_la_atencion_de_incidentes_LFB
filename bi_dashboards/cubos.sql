SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

CREATE OR ALTER VIEW dbo.CuboIncidentes AS
SELECT
    i.AnioFuente AS Anio,
    f.Mes,
    g.BoroughNombre AS Borough,
    t.Grupo,
    p.Categoria,
    CASE WHEN GROUPING(p.Categoria) = 1 THEN 'mes' ELSE 'inmueble' END AS Nivel,
    COUNT_BIG(*) AS Incidentes,
    COUNT_BIG(CASE WHEN t.Grupo = N'False Alarm' THEN 1 END) AS FalsasAlarmas,
    SUM(CAST(i.PrimerArriboSeg AS bigint)) AS SumaPrimeraLlegada,
    COUNT_BIG(i.PrimerArriboSeg) AS ConPrimeraLlegada,
    SUM(CAST(i.SegundoArriboSeg AS bigint)) AS SumaSegundaLlegada,
    COUNT_BIG(i.SegundoArriboSeg) AS ConSegundaLlegada,
    SUM(CAST(i.NumBombas AS bigint)) AS Bombas,
    SUM(CAST(i.MinutosBombaRedondeados AS bigint)) AS MinutosBomba,
    SUM(i.CostoNocionalGBP) AS CostoNocionalGBP
FROM dbo.FactIncidente AS i
INNER JOIN dbo.DimFecha AS f ON i.FechaKey = f.FechaKey
INNER JOIN dbo.DimGeografia AS g ON i.GeografiaKey = g.GeografiaKey
INNER JOIN dbo.DimTipoIncidente AS t ON i.TipoIncidenteKey = t.TipoIncidenteKey
INNER JOIN dbo.DimTipoPropiedad AS p ON i.TipoPropiedadKey = p.TipoPropiedadKey
GROUP BY GROUPING SETS (
    (i.AnioFuente, f.Mes, g.BoroughNombre, t.Grupo),
    (i.AnioFuente, g.BoroughNombre, t.Grupo, p.Categoria)
);
GO

CREATE OR ALTER VIEW dbo.CuboMovilizaciones AS
SELECT
    m.AnioFuente AS Anio,
    g.BoroughNombre AS Borough,
    t.Grupo,
    d.Codigo AS MotivoCodigo,
    d.Descripcion AS Motivo,
    CASE WHEN GROUPING(d.Codigo) = 1 THEN 'total' ELSE 'motivo' END AS Nivel,
    COUNT_BIG(*) AS Movilizaciones,
    COUNT_BIG(CASE WHEN m.TieneIncidente = 0 THEN 1 END) AS SinIncidente,
    SUM(CAST(m.LlegadaSeg AS bigint)) AS SumaLlegada,
    COUNT_BIG(m.LlegadaSeg) AS ConLlegada
FROM dbo.FactMovilizacion AS m
INNER JOIN dbo.DimGeografia AS g ON m.GeografiaKey = g.GeografiaKey
INNER JOIN dbo.DimTipoIncidente AS t ON m.TipoIncidenteKey = t.TipoIncidenteKey
INNER JOIN dbo.DimMotivoDemora AS d ON m.MotivoDemoraKey = d.MotivoDemoraKey
GROUP BY GROUPING SETS (
    (m.AnioFuente, g.BoroughNombre, t.Grupo),
    (m.AnioFuente, g.BoroughNombre, t.Grupo, d.Codigo, d.Descripcion)
);
GO
