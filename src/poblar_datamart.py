"""ETL DE LONDON FIRE BRIGADE

Lee los archivos originales del periodo 2021 a 2025 y carga el datamart
LondonFireBrigadeDM. La base se crea previamente en SQL Server.

Orden de carga
  1. Leer y limpiar los archivos.
  2. Conectar al datamart y crear las tablas que falten.
  3. Vaciar las tablas si se pidió una recarga.
  4. Cargar las dimensiones y recuperar sus claves.
  5. Cargar los hechos, comprobar los conteos y cerrar la conexión.
"""

import argparse
import json
from pathlib import Path

import pandas as pd
import pyodbc


PERIODO = range(2021, 2026)
BASE_DESTINO = 'LondonFireBrigadeDM'
CARPETA_DATOS = Path(__file__).resolve().parents[1] / 'data' / 'originales'
DESCONOCIDO = 'Desconocido'

TIPO_INCIDENTE = ['Grupo', 'Clasificacion', 'ServicioEspecial']
TIPO_PROPIEDAD = ['Categoria', 'Tipo']
GEOGRAFIA = ['BoroughCodigo', 'BoroughNombre', 'WardCodigo', 'WardNombre', 'DistritoPostal']
CLAVES_COMPARTIDAS = ['FechaKey', 'HoraKey', 'TipoIncidenteKey', 'TipoPropiedadKey', 'GeografiaKey']

CAMPOS_INCIDENTES = {
    'IncidentGroup': 'Grupo',
    'StopCodeDescription': 'Clasificacion',
    'SpecialServiceType': 'ServicioEspecial',
    'PropertyCategory': 'Categoria',
    'PropertyType': 'Tipo',
    'IncGeo_BoroughCode': 'BoroughCodigo',
    'IncGeo_BoroughName': 'BoroughNombre',
    'IncGeo_WardCode': 'WardCodigo',
    'IncGeo_WardName': 'WardNombre',
    'Postcode_district': 'DistritoPostal',
    'FirstPumpArriving_AttendanceTime': 'PrimerArriboSeg',
    'SecondPumpArriving_AttendanceTime': 'SegundoArriboSeg',
    'NumStationsWithPumpsAttending': 'NumEstaciones',
    'NumPumpsAttending': 'NumBombas',
    'PumpMinutesRounded': 'MinutosBombaRedondeados',
    'Notional Cost (£)': 'CostoNocionalGBP',
    'NumCalls': 'NumLlamadas',
}
CAMPOS_MOVILIZACIONES = {
    'DeployedFromStation_Code': 'CodigoEstacion',
    'DeployedFromStation_Name': 'NombreEstacion',
    'DeployedFromLocation': 'Origen',
    'DelayCodeId': 'CodigoDemora',
    'DelayCode_Description': 'DescripcionDemora',
    'Resource_Code': 'ResourceCodigo',
    'DateAndTimeMobilised': 'FechaHoraMovilizada',
    'TurnoutTimeSeconds': 'SalidaSeg',
    'TravelTimeSeconds': 'ViajeSeg',
    'AttendanceTimeSeconds': 'LlegadaSeg',
}
MEDIDAS_INCIDENTES = [
    'PrimerArriboSeg', 'SegundoArriboSeg', 'NumEstaciones', 'NumBombas',
    'MinutosBombaRedondeados', 'CostoNocionalGBP', 'NumLlamadas',
]
FACT_INCIDENTE = ['IncidentNumber', 'AnioFuente', *CLAVES_COMPARTIDAS, *MEDIDAS_INCIDENTES, 'TieneMovilizacion']
FACT_MOVILIZACION = [
    'ResourceMobilisationId', 'AnioFuente', 'IncidentNumber', *CLAVES_COMPARTIDAS,
    'EstacionKey', 'OrigenDespliegueKey', 'MotivoDemoraKey', 'ResourceCodigo',
    'PerformanceReporting', 'FechaHoraMovilizada', 'SalidaSeg', 'ViajeSeg', 'LlegadaSeg', 'TieneIncidente',
]


# CONEXIÓN AL DESTINO
def get_connection_destino():
    """Devuelve la conexión abierta, o None si SQL Server no se pudo conectar."""
    try:
        conn = pyodbc.connect(
            'DRIVER={ODBC Driver 18 for SQL Server};'
            r'SERVER=.\SQLEXPRESS;'
            f'DATABASE={BASE_DESTINO};'  # El mismo nombre que usa el tablero.
            'Trusted_Connection=yes;'
            'Encrypt=yes;'
            'TrustServerCertificate=yes;'
        )
        print('Conexión a destino exitosa.')
        return conn
    except pyodbc.Error as e:
        print(f'Error de conexión al destino: {e}')
        return None


# ESQUEMA Y LIMPIEZA DEL DATAMART
def create_datamart_schema(dest_cursor):
    """Ejecuta los CREATE TABLE del modelo en la base destino."""
    esquema = Path(__file__).parent / '01_crear_datamart.sql'
    dest_cursor.execute(esquema.read_text(encoding='utf-8'))


def clean_datamart(dest_cursor):
    # Los hechos se borran primero porque sus claves apuntan a las dimensiones.
    dest_cursor.execute("""
        DELETE FROM dbo.FactMovilizacion;
        DELETE FROM dbo.FactIncidente;
        DELETE FROM dbo.DimMotivoDemora;
        DELETE FROM dbo.DimOrigenDespliegue;
        DELETE FROM dbo.DimEstacion;
        DELETE FROM dbo.DimGeografia;
        DELETE FROM dbo.DimTipoPropiedad;
        DELETE FROM dbo.DimTipoIncidente;
        DELETE FROM dbo.DimHora;
        DELETE FROM dbo.DimFecha;
    """)


# LECTURA Y LIMPIEZA DE LOS ARCHIVOS
def leer_archivos(*nombres):
    tablas = []
    anios = [str(anio) for anio in PERIODO]
    for nombre in nombres:
        ruta = CARPETA_DATOS / nombre
        print(f'Leyendo {ruta.name}...', flush=True)
        # Se leen los datos como texto para conservar los códigos y los valores NULL de la fuente.
        if ruta.suffix == '.csv':
            df = pd.read_csv(ruta, encoding='utf-8-sig', dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(ruta, engine='calamine', dtype=str, keep_default_na=False)
        tablas.append(df.loc[df['CalYear'].isin(anios)])
    return pd.concat(tablas, ignore_index=True)


def conteo_por_anio(df):
    return {int(anio): int(filas) for anio, filas in df['CalYear'].value_counts().items()}


def limpiar_datos(df, id_columna, reporte):
    reporte['filas_origen'] = conteo_por_anio(df)

    # Primero se quitan las copias idénticas, comparando toda la fila.
    duplicados = df.duplicated()
    reporte['duplicados_exactos'] = conteo_por_anio(df.loc[duplicados])
    df = df.loc[~duplicados].copy()
    df[id_columna] = df[id_columna].str.strip()

    # Se descartan los ID vacíos y todas las versiones en conflicto de un mismo ID.
    sin_id = df[id_columna].isna() | df[id_columna].isin(['', 'NULL'])
    conflictos = ~sin_id & df[id_columna].duplicated(keep=False)
    reporte['sin_identificador'] = conteo_por_anio(df.loc[sin_id])
    reporte['filas_en_conflicto'] = conteo_por_anio(df.loc[conflictos])
    df = df.loc[~(sin_id | conflictos)].copy()
    reporte['filas_validas'] = conteo_por_anio(df)
    return df


def normalizar_texto(df, columnas):
    for columna in columnas:
        valores = df[columna].str.strip()
        df[columna] = valores.mask(valores.isin(['', 'NULL']), DESCONOCIDO)


def enteros_no_negativos(valores):
    # errors='coerce' convierte los valores que no se pueden leer como número en datos faltantes.
    numeros = pd.to_numeric(valores, errors='coerce')
    return numeros.where(numeros.between(0, 2147483647) & numeros.mod(1).eq(0)).astype('Int32')


def preparar_incidentes(df):
    df = df[['IncidentNumber', 'CalYear', 'DateOfCall', 'HourOfCall', *CAMPOS_INCIDENTES]].rename(
        columns={**CAMPOS_INCIDENTES, 'CalYear': 'AnioFuente'}
    )
    df['AnioFuente'] = df['AnioFuente'].astype(int)
    fecha = pd.to_datetime(df['DateOfCall'].str[:10], format='%Y-%m-%d', errors='coerce')
    fecha = fecha.where(fecha.dt.year.eq(df['AnioFuente']))
    df['FechaKey'] = (fecha.dt.year * 10000 + fecha.dt.month * 100 + fecha.dt.day).fillna(0).astype(int)
    hora = enteros_no_negativos(df['HourOfCall'])
    df['HoraKey'] = (hora.where(hora.lt(24)) + 1).fillna(0).astype(int)
    normalizar_texto(df, TIPO_INCIDENTE + TIPO_PROPIEDAD + GEOGRAFIA)
    df.loc[df['Grupo'].ne('Special Service') & df['Grupo'].ne(DESCONOCIDO), 'ServicioEspecial'] = 'No aplica'
    for columna in GEOGRAFIA:
        df[columna] = df[columna].where(df[columna].eq(DESCONOCIDO), df[columna].str.upper())
    for columna in MEDIDAS_INCIDENTES:
        if columna == 'CostoNocionalGBP':
            df[columna] = pd.to_numeric(df[columna], errors='coerce').round(2)
        else:
            df[columna] = enteros_no_negativos(df[columna])
    for columna in ['PrimerArriboSeg', 'SegundoArriboSeg']:
        df[columna] = df[columna].where(df[columna].gt(0))
    return df.drop(columns=['DateOfCall', 'HourOfCall'])


def preparar_movilizaciones(df):
    df = df[['IncidentNumber', 'CalYear', 'ResourceMobilisationId', 'PerformanceReporting', *CAMPOS_MOVILIZACIONES]].rename(
        columns={**CAMPOS_MOVILIZACIONES, 'CalYear': 'AnioFuente'}
    )
    df['AnioFuente'] = df['AnioFuente'].astype(int)
    df['ResourceMobilisationId'] = df['ResourceMobilisationId'].astype('int64')
    id_incidente = df['IncidentNumber'].str.strip()
    df['IncidentNumber'] = id_incidente.mask(id_incidente.isin(['', 'NULL']))
    normalizar_texto(df, ['CodigoEstacion', 'NombreEstacion', 'DescripcionDemora'])
    df['OrigenDespliegueKey'] = df['Origen'].map({'Home Station': 1, 'Other Station': 2}).fillna(0).astype(int)
    df['MotivoDemoraKey'] = enteros_no_negativos(df['CodigoDemora']).fillna(0)
    marca = df['FechaHoraMovilizada']
    df['FechaHoraMovilizada'] = pd.to_datetime(marca, format='mixed', dayfirst=True, errors='coerce')
    for columna in ['SalidaSeg', 'ViajeSeg', 'LlegadaSeg']:
        df[columna] = enteros_no_negativos(df[columna])
    return df


# CARGA DE DIMENSIONES Y HECHOS
def insertar_lotes(dest_cursor, query_insert, df):
    # Los signos ? son parámetros. executemany envía los valores de varias filas juntos.
    dest_cursor.fast_executemany = True
    for inicio in range(0, len(df), 10000):
        bloque = df.iloc[inicio:inicio + 10000].astype(object)
        # pyodbc envía None como NULL en SQL Server.
        bloque = bloque.where(pd.notna(bloque), None)
        if 'FechaHoraMovilizada' in bloque:
            bloque['FechaHoraMovilizada'] = bloque['FechaHoraMovilizada'].map(
                lambda fecha: fecha.to_pydatetime() if fecha is not None else None
            ).astype(object).where(bloque['FechaHoraMovilizada'].notna(), None)
        filas = list(bloque.itertuples(index=False, name=None))
        dest_cursor.executemany(query_insert, filas)


def dimension_identidad(dest_cursor, tabla, clave, df, query_insert):
    columnas = df.columns.tolist()
    desconocido = {columna: DESCONOCIDO for columna in columnas}
    catalogo = df.drop_duplicates().sort_values(columnas)
    catalogo = catalogo.loc[~catalogo.eq(pd.Series(desconocido)).all(axis=1)]
    campos = ', '.join([clave, *columnas])
    parametros = ', '.join('?' for _ in columnas)
    dest_cursor.execute(f'SET IDENTITY_INSERT dbo.{tabla} ON')
    dest_cursor.execute(
        f'INSERT INTO dbo.{tabla} ({campos}) VALUES (0, {parametros})', *desconocido.values(),
    )
    dest_cursor.execute(f'SET IDENTITY_INSERT dbo.{tabla} OFF')
    for _, fila in catalogo.iterrows():
        dest_cursor.execute(query_insert, *fila.tolist())
    # SQL Server asigna las claves al insertar. Las volvemos a leer para usarlas en los hechos.
    dest_cursor.execute(f'SELECT * FROM dbo.{tabla}')
    return pd.DataFrame.from_records(
        [tuple(fila) for fila in dest_cursor.fetchall()], columns=[col[0] for col in dest_cursor.description]
    )


def cargar_dimensiones(dest_cursor, incidentes, movilizaciones):
    # DimFecha cubre todos los días del periodo, aunque no tengan incidentes.
    print('Cargando DimFecha...')
    df_fechas = pd.DataFrame({'Fecha': pd.date_range('2021-01-01', '2025-12-31')})
    query_fecha = """
        INSERT INTO dbo.DimFecha (FechaKey, Fecha, Anio, Trimestre, Mes, Dia, DiaSemana)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    dest_cursor.execute('INSERT INTO dbo.DimFecha (FechaKey) VALUES (?)', 0)
    for _, fila in df_fechas.iterrows():
        fecha = fila['Fecha']
        dest_cursor.execute(query_fecha, int(fecha.strftime('%Y%m%d')), fecha.date(),
                            fecha.year, fecha.quarter, fecha.month, fecha.day, fecha.day_of_week + 1)

    print('Cargando DimHora...')
    df_horas = pd.DataFrame({
        'Hora': range(24),
        'Franja': ['Madrugada'] * 6 + ['Mañana'] * 6 + ['Tarde'] * 6 + ['Noche'] * 6,
    })
    query_hora = 'INSERT INTO dbo.DimHora (HoraKey, Hora, Franja) VALUES (?, ?, ?)'
    dest_cursor.execute(query_hora, 0, None, DESCONOCIDO)
    for _, fila in df_horas.iterrows():
        hora = int(fila['Hora'])
        dest_cursor.execute(query_hora, hora + 1, hora, str(fila['Franja']))

    print('Cargando DimTipoIncidente...')
    query_tipo_incidente = """
        INSERT INTO dbo.DimTipoIncidente (Grupo, Clasificacion, ServicioEspecial)
        VALUES (?, ?, ?)
    """
    dim_incidente = dimension_identidad(
        dest_cursor, 'DimTipoIncidente', 'TipoIncidenteKey', incidentes[TIPO_INCIDENTE], query_tipo_incidente,
    )

    print('Cargando DimTipoPropiedad...')
    query_tipo_propiedad = 'INSERT INTO dbo.DimTipoPropiedad (Categoria, Tipo) VALUES (?, ?)'
    dim_propiedad = dimension_identidad(
        dest_cursor, 'DimTipoPropiedad', 'TipoPropiedadKey', incidentes[TIPO_PROPIEDAD], query_tipo_propiedad,
    )

    print('Cargando DimGeografia...')
    query_geografia = """
        INSERT INTO dbo.DimGeografia (BoroughCodigo, BoroughNombre, WardCodigo, WardNombre, DistritoPostal)
        VALUES (?, ?, ?, ?, ?)
    """
    dim_geografia = dimension_identidad(
        dest_cursor, 'DimGeografia', 'GeografiaKey', incidentes[GEOGRAFIA], query_geografia,
    )

    print('Cargando DimEstacion...')
    estaciones = movilizaciones.loc[movilizaciones['CodigoEstacion'].ne(DESCONOCIDO)].rename(
        columns={'CodigoEstacion': 'Codigo', 'NombreEstacion': 'Nombre'}
    )
    estaciones = (
        estaciones.sort_values('AnioFuente', kind='stable')[['Codigo', 'Nombre']]
        .drop_duplicates('Codigo', keep='last')
    )
    query_estacion = 'INSERT INTO dbo.DimEstacion (Codigo, Nombre) VALUES (?, ?)'
    dim_estacion = dimension_identidad(dest_cursor, 'DimEstacion', 'EstacionKey', estaciones, query_estacion)
    # SQL Server genera EstacionKey; zip arma el diccionario para buscarla por código.
    codigo_to_id = dict(zip(dim_estacion['Codigo'], dim_estacion['EstacionKey']))

    print('Cargando DimOrigenDespliegue...')
    query_origen = 'INSERT INTO dbo.DimOrigenDespliegue (OrigenDespliegueKey, Origen) VALUES (?, ?)'
    for clave, origen in enumerate([DESCONOCIDO, 'Home Station', 'Other Station']):
        dest_cursor.execute(query_origen, clave, origen)

    print('Cargando DimMotivoDemora...')
    demoras = movilizaciones.loc[movilizaciones['MotivoDemoraKey'].ne(0), ['MotivoDemoraKey', 'DescripcionDemora']]
    demoras = demoras.drop_duplicates().rename(columns={'DescripcionDemora': 'Descripcion'})
    if demoras['MotivoDemoraKey'].duplicated().any():
        raise ValueError('Hay códigos de demora con más de una descripción. Revisa el catálogo de la fuente.')
    query_demora = 'INSERT INTO dbo.DimMotivoDemora (MotivoDemoraKey, Codigo, Descripcion) VALUES (?, ?, ?)'
    dest_cursor.execute(query_demora, 0, DESCONOCIDO, DESCONOCIDO)
    for _, fila in demoras.iterrows():
        codigo = int(fila['MotivoDemoraKey'])
        dest_cursor.execute(query_demora, codigo, str(codigo), str(fila['Descripcion']))

    # Las tres dimensiones del incidente se buscan por todas las columnas de su clave.
    incidentes = incidentes.merge(dim_incidente, on=TIPO_INCIDENTE, how='left', validate='many_to_one')
    incidentes = incidentes.merge(dim_propiedad, on=TIPO_PROPIEDAD, how='left', validate='many_to_one')
    incidentes = incidentes.merge(dim_geografia, on=GEOGRAFIA, how='left', validate='many_to_one')
    movilizaciones['EstacionKey'] = movilizaciones['CodigoEstacion'].map(codigo_to_id)
    if incidentes[CLAVES_COMPARTIDAS].isna().any().any() or movilizaciones['EstacionKey'].isna().any():
        raise ValueError('Hay claves de dimensiones sin recuperar después de la carga.')
    return incidentes, movilizaciones


def cargar_hechos(dest_cursor, incidentes, movilizaciones):
    # Cada movilización hereda las claves de contexto de su incidente del mismo año.
    enlace = ['IncidentNumber', 'AnioFuente']
    enlazadas = movilizaciones.merge(
        incidentes[enlace + CLAVES_COMPARTIDAS], on=enlace, how='left',
        validate='many_to_one', indicator=True,
    )
    tienen_incidente = enlazadas['_merge'].eq('both')
    enlazadas['TieneIncidente'] = tienen_incidente.astype(int)
    enlazadas[CLAVES_COMPARTIDAS] = enlazadas[CLAVES_COMPARTIDAS].fillna(0).astype(int)
    con_mov = pd.MultiIndex.from_frame(enlazadas.loc[tienen_incidente, enlace].drop_duplicates())
    incidentes['TieneMovilizacion'] = pd.MultiIndex.from_frame(incidentes[enlace]).isin(con_mov).astype(int)

    print(f'Cargando FactIncidente ({len(incidentes):,} filas)...', flush=True)
    query_fact_incidente = """
        INSERT INTO dbo.FactIncidente (
            IncidentNumber, AnioFuente, FechaKey, HoraKey, TipoIncidenteKey, TipoPropiedadKey, GeografiaKey,
            PrimerArriboSeg, SegundoArriboSeg, NumEstaciones, NumBombas, MinutosBombaRedondeados,
            CostoNocionalGBP, NumLlamadas, TieneMovilizacion
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    insertar_lotes(dest_cursor, query_fact_incidente, incidentes[FACT_INCIDENTE])

    print(f'Cargando FactMovilizacion ({len(enlazadas):,} filas)...', flush=True)
    query_fact_movilizacion = """
        INSERT INTO dbo.FactMovilizacion (
            ResourceMobilisationId, AnioFuente, IncidentNumber, FechaKey, HoraKey, TipoIncidenteKey,
            TipoPropiedadKey, GeografiaKey, EstacionKey, OrigenDespliegueKey, MotivoDemoraKey,
            ResourceCodigo, PerformanceReporting, FechaHoraMovilizada, SalidaSeg, ViajeSeg, LlegadaSeg, TieneIncidente
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    insertar_lotes(dest_cursor, query_fact_movilizacion, enlazadas[FACT_MOVILIZACION])


def validar_carga(cursor, reporte):
    cursor.execute((Path(__file__).parent / '03_validar_carga.sql').read_text(encoding='utf-8'))
    columnas = [col[0] for col in cursor.description]
    filas = [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    for fila in filas:
        anio = fila['AnioFuente']
        if fila['Incidentes'] != reporte['incidentes']['filas_validas'][anio]:
            raise ValueError(f'El conteo de incidentes en SQL difiere de la carga para {anio}.')
        if fila['Movilizaciones'] != reporte['movilizaciones']['filas_validas'][anio]:
            raise ValueError(f'El conteo de movilizaciones en SQL difiere de la carga para {anio}.')
    if {fila['AnioFuente'] for fila in filas} != set(PERIODO):
        raise ValueError('La base debe contener los cinco años del estudio.')
    reporte['validacion_sql'] = filas


# PROGRAMA PRINCIPAL
def main():
    parser = argparse.ArgumentParser(description='Carga el datamart de London Fire Brigade 2021–2025.')
    parser.add_argument('--recargar', action='store_true', help='Reemplaza la carga anterior del datamart')
    args = parser.parse_args()

    # PASO 1. LEER Y LIMPIAR LOS ARCHIVOS ORIGINALES
    reporte = {'periodo': [min(PERIODO), max(PERIODO)], 'incidentes': {}, 'movilizaciones': {}}
    df_incidentes = leer_archivos('incidentes_2018_2023.xlsx', 'incidentes_2024_hasta_julio_2026.xlsx')
    df_incidentes = limpiar_datos(df_incidentes, 'IncidentNumber', reporte['incidentes'])
    df_incidentes = preparar_incidentes(df_incidentes)

    df_movilizaciones = leer_archivos('movilizaciones_2021_2024.csv', 'movilizaciones_2025_hasta_julio_2026.csv')
    df_movilizaciones = limpiar_datos(df_movilizaciones, 'ResourceMobilisationId', reporte['movilizaciones'])
    df_movilizaciones = preparar_movilizaciones(df_movilizaciones)

    # PASO 2. CONECTAR AL DESTINO Y CREAR LAS TABLAS
    dest_conn = get_connection_destino()
    if dest_conn is None:
        raise SystemExit(1)
    try:
        # El cursor ejecuta las consultas e INSERT sobre la conexión destino.
        dest_cursor = dest_conn.cursor()
        # SQL Server libera este bloqueo al hacer commit o rollback.
        estado = dest_cursor.execute("""
            SET NOCOUNT ON;
            DECLARE @estado int;
            EXEC @estado = sys.sp_getapplock
                @Resource = 'LondonFireBrigadeCarga', @LockMode = 'Exclusive', @LockTimeout = 0;
            SELECT @estado;
        """).fetchone()[0]
        if estado < 0:
            raise RuntimeError('Ya hay otra carga del datamart en ejecución.')
        create_datamart_schema(dest_cursor)
        # PASO 3. VACIAR LAS TABLAS PARA UNA RECARGA COMPLETA
        existe = dest_cursor.execute('SELECT COUNT_BIG(*) FROM dbo.DimFecha').fetchone()[0] > 0
        if existe and not args.recargar:
            raise ValueError('El datamart ya está poblado. Usa --recargar para reemplazar esa carga.')
        if existe:
            clean_datamart(dest_cursor)

        # PASO 4. CARGAR LAS DIMENSIONES Y RECUPERAR SUS CLAVES
        print('Cargando dimensiones y recuperando sus claves...', flush=True)
        df_incidentes, df_movilizaciones = cargar_dimensiones(dest_cursor, df_incidentes, df_movilizaciones)

        # PASO 5. CARGAR LOS HECHOS Y REVISAR LOS CONTEOS
        cargar_hechos(dest_cursor, df_incidentes, df_movilizaciones)
        validar_carga(dest_cursor, reporte)
        # Se confirma todo junto para conservar la carga anterior si algo falla.
        dest_conn.commit()
    except Exception:
        dest_conn.rollback()
        raise
    finally:
        dest_conn.close()

    Path('calidad_carga.json').write_text(json.dumps(reporte, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Carga verificada. Reporte guardado en calidad_carga.json.', flush=True)


if __name__ == '__main__':
    main()
