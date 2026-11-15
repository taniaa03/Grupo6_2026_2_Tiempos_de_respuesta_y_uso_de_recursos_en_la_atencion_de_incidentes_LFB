from contextlib import closing
import warnings

import pandas as pd


ETIQUETAS = {
    'Primary Fire': 'Incendio primario',
    'Secondary Fire': 'Incendio secundario',
    'Chimney Fire': 'Incendio de chimenea',
    'Late Call': 'Aviso tardío',
    'AFA': 'Alarma automática (AFA)',
    'False alarm - Good intent': 'Aviso de buena fe',
    'False alarm - Malicious': 'Aviso malintencionado',
    'Alleged Fire Risk': 'Presunto riesgo de incendio',
    'Effecting entry/exit': 'Facilitar el acceso o la salida',
    'Flooding': 'Inundación',
    'Lift Release': 'Rescate de ascensor',
    'No action (not false alarm)': 'Sin intervención',
    'RTC': 'Colisión de tránsito',
    'Assist other agencies': 'Asistencia a otras entidades',
    'Hazardous Materials incident': 'Incidente con materiales peligrosos',
    'Making Safe (not RTC)': 'Puesta en seguridad (sin colisión de tránsito)',
    'Animal assistance incidents': 'Asistencia a animales',
    'Medical Incident': 'Incidente médico',
    'Advice Only': 'Orientación',
    'Removal of objects from people': 'Retiro de objetos de personas',
    'Spills and Leaks (not RTC)': 'Derrames y fugas (sin colisión de tránsito)',
    'Other rescue/release of persons': 'Otros rescates de personas',
    'Suicide/attempts': 'Suicidio o intento',
    'Other Transport incident': 'Otro incidente de transporte',
    'Evacuation (no fire)': 'Evacuación sin incendio',
    'Rescue or evacuation from water': 'Rescate o evacuación del agua',
    'Stand By': 'En espera',
    'Water provision': 'Suministro de agua',
}


def columna_subgrupo(grupo):
    return 't.ServicioEspecial' if grupo == 'Special Service' else 't.Clasificacion'


def etiqueta_subgrupo(subgrupo):
    return ETIQUETAS.get(subgrupo, subgrupo)


def subgrupos_registrados(conectar):
    sql = '''
        SELECT DISTINCT t.Grupo,
            CASE WHEN t.Grupo = N'Special Service' THEN t.ServicioEspecial ELSE t.Clasificacion END AS Subgrupo
        FROM dbo.DimTipoIncidente AS t
        WHERE t.Grupo IN (N'Fire', N'False Alarm', N'Special Service')
          AND EXISTS (SELECT 1 FROM dbo.FactIncidente AS i WHERE i.TipoIncidenteKey = t.TipoIncidenteKey);
    '''
    grupos = {}
    with closing(conectar()) as conn:
        for grupo, subgrupo in conn.cursor().execute(sql):
            if subgrupo and subgrupo.strip().casefold() not in ('', 'desconocido', 'no aplica'):
                grupos.setdefault(grupo, []).append(subgrupo)
    return {grupo: sorted(opciones, key=etiqueta_subgrupo) for grupo, opciones in grupos.items()}


def agregados_subgrupo(conectar, grupo, subgrupo):
    campo = columna_subgrupo(grupo)
    incidentes = f'''
        SELECT i.AnioFuente AS Anio, f.Mes, g.BoroughNombre AS Borough, t.Grupo, p.Categoria,
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
        WHERE t.Grupo = ? AND {campo} = ?
        GROUP BY GROUPING SETS (
            (i.AnioFuente, f.Mes, g.BoroughNombre, t.Grupo),
            (i.AnioFuente, g.BoroughNombre, t.Grupo, p.Categoria)
        );
    '''
    movilizaciones = f'''
        SELECT m.AnioFuente AS Anio, g.BoroughNombre AS Borough, t.Grupo,
            d.Codigo AS MotivoCodigo, d.Descripcion AS Motivo,
            CASE WHEN GROUPING(d.Codigo) = 1 THEN 'total' ELSE 'motivo' END AS Nivel,
            COUNT_BIG(*) AS Movilizaciones,
            COUNT_BIG(CASE WHEN m.TieneIncidente = 0 THEN 1 END) AS SinIncidente,
            SUM(CAST(m.LlegadaSeg AS bigint)) AS SumaLlegada,
            COUNT_BIG(m.LlegadaSeg) AS ConLlegada
        FROM dbo.FactMovilizacion AS m
        INNER JOIN dbo.DimGeografia AS g ON m.GeografiaKey = g.GeografiaKey
        INNER JOIN dbo.DimTipoIncidente AS t ON m.TipoIncidenteKey = t.TipoIncidenteKey
        INNER JOIN dbo.DimMotivoDemora AS d ON m.MotivoDemoraKey = d.MotivoDemoraKey
        WHERE t.Grupo = ? AND {campo} = ?
        GROUP BY GROUPING SETS (
            (m.AnioFuente, g.BoroughNombre, t.Grupo),
            (m.AnioFuente, g.BoroughNombre, t.Grupo, d.Codigo, d.Descripcion)
        );
    '''
    with closing(conectar()) as conn, warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy connectable')
        return tuple(pd.read_sql(consulta, conn, params=(grupo, subgrupo), coerce_float=False)
                     for consulta in (incidentes, movilizaciones))
