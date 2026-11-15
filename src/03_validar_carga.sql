WITH incidentes AS (
    SELECT AnioFuente, COUNT_BIG(*) AS Incidentes,
           SUM(CONVERT(int, TieneMovilizacion)) AS IncidentesConMovilizacion,
           COUNT_BIG(PrimerArriboSeg) AS PrimerArriboInformado,
           COUNT_BIG(SegundoArriboSeg) AS SegundoArriboInformado,
           SUM(CASE WHEN FechaKey = 0 THEN 1 ELSE 0 END) AS IncidentesSinFecha
    FROM dbo.FactIncidente
    GROUP BY AnioFuente
), movilizaciones AS (
    SELECT AnioFuente, COUNT_BIG(*) AS Movilizaciones,
           SUM(CONVERT(int, TieneIncidente)) AS MovilizacionesConIncidente,
           SUM(CASE WHEN TieneIncidente = 0 THEN 1 ELSE 0 END) AS MovilizacionesSinIncidente,
           COUNT_BIG(LlegadaSeg) AS LlegadaInformada,
           SUM(CASE WHEN SalidaSeg IS NOT NULL AND ViajeSeg IS NOT NULL AND LlegadaSeg IS NOT NULL
                         AND CONVERT(bigint, SalidaSeg) + ViajeSeg <> LlegadaSeg THEN 1 ELSE 0 END) AS DiferenciaDeTiempos
    FROM dbo.FactMovilizacion
    GROUP BY AnioFuente
)
SELECT i.AnioFuente, i.Incidentes, i.IncidentesConMovilizacion,
       i.PrimerArriboInformado, i.SegundoArriboInformado, i.IncidentesSinFecha,
       m.Movilizaciones, m.MovilizacionesConIncidente, m.MovilizacionesSinIncidente,
       m.LlegadaInformada, m.DiferenciaDeTiempos
FROM incidentes AS i
INNER JOIN movilizaciones AS m ON m.AnioFuente = i.AnioFuente
ORDER BY i.AnioFuente;
