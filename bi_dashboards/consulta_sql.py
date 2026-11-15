import logging

import pyodbc
from sqlglot import ErrorLevel, exp, parse
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import traverse_scope


# La conexión de la consola cambia de usuario hasta que se cierra la sesión.
pyodbc.pooling = False

LOG = logging.getLogger(__name__)
MAX_FILAS = 200
MAX_CARACTERES = 8000
TIEMPO_LIMITE = 10
TABLAS = frozenset(nombre.casefold() for nombre in (
    'DimFecha', 'DimHora', 'DimTipoIncidente', 'DimTipoPropiedad', 'DimGeografia',
    'DimEstacion', 'DimOrigenDespliegue', 'DimMotivoDemora', 'FactIncidente',
    'FactMovilizacion', 'CuboIncidentes', 'CuboMovilizaciones',
))

ESTRUCTURAS = (
    exp.Select, exp.Subquery, exp.Union, exp.Intersect, exp.Except,
    exp.CTE, exp.With, exp.From, exp.Table, exp.TableAlias, exp.Join, exp.Alias,
    exp.Identifier, exp.Column, exp.Star, exp.Literal, exp.National, exp.HexString,
    exp.Boolean, exp.Null, exp.Tuple, exp.Where, exp.Group, exp.Having, exp.Order,
    exp.Ordered, exp.Distinct, exp.Limit, exp.LimitOptions, exp.Offset, exp.Fetch,
    exp.Paren, exp.Case, exp.And, exp.Or, exp.Not, exp.EQ, exp.NEQ, exp.GT,
    exp.GTE, exp.LT, exp.LTE, exp.Is, exp.In, exp.Between, exp.Like, exp.Escape,
    exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Mod, exp.Neg, exp.DataType,
    exp.DataTypeParam, exp.Window, exp.WindowSpec, exp.WithinGroup, exp.Cube,
    exp.Rollup, exp.GroupingSets,
)
FUNCIONES = frozenset('''
    ABS AVG CAST CEIL COALESCE CONCAT CONCAT_WS CONVERT COUNT COUNT_BIG DATE_ADD
    DATE_FROM_PARTS DATE_TRUNC DATEDIFF DATEPART DATETRUNC DAY DENSE_RANK EOMONTH
    EXISTS EXTRACT FIRST_VALUE FLOOR GROUP_CONCAT GROUPING GROUPING_ID IF LAG
    LAST_VALUE LEAD LEFT LENGTH LOWER LTRIM MAX MIN MONTH NULLIF PERCENTILE_CONT
    PERCENTILE_DISC POWER RANK REPLACE RIGHT ROUND ROW_NUMBER RTRIM SQRT STDDEV
    STDDEV_POP STR_POSITION SUBSTRING SUM TIME_STR_TO_TIME TIME_TO_STR TRIM
    TRY_CAST TRY_CONVERT TS_OR_DS_TO_DATE UPPER VARIANCE VARIANCE_POP YEAR
'''.split())
PARTES_FECHA = frozenset('''
    year yy yyyy quarter qq q month mm m dayofyear dy y day dd d week wk ww
    weekday dw w hour hh minute mi n second ss s millisecond ms microsecond
    mcs nanosecond ns tzoffset tz iso_week isowk isoww
'''.split())


class ErrorConsulta(Exception):
    pass


def normalizar_consulta(consulta):
    if not isinstance(consulta, str) or not consulta.strip():
        raise ErrorConsulta('Escribe una consulta SELECT para ejecutarla.')
    if len(consulta) > MAX_CARACTERES:
        raise ErrorConsulta(f'La consulta admite hasta {MAX_CARACTERES:,} caracteres.')
    try:
        sentencias = [
            sentencia for sentencia in parse(consulta, read='tsql', error_level=ErrorLevel.RAISE)
            if sentencia is not None and not isinstance(sentencia, exp.Semicolon)
        ]
        if len(sentencias) != 1 or not isinstance(sentencias[0], (exp.Select, exp.SetOperation)):
            raise ErrorConsulta('Ejecuta una sola consulta SELECT a la vez.')

        sentencia = sentencias[0]
        for nodo in sentencia.walk():
            if isinstance(nodo, ESTRUCTURAS):
                continue
            if isinstance(nodo, exp.Var) and nodo.name.casefold() in PARTES_FECHA:
                continue
            if isinstance(nodo, exp.Func):
                nombre = nodo.name.upper() if isinstance(nodo, exp.Anonymous) else nodo.sql_name()
                if nombre in FUNCIONES:
                    continue
                raise ErrorConsulta('Esa función no está habilitada para consultar el datamart.')
            raise ErrorConsulta('La consola admite SELECT, uniones y agregaciones de solo lectura.')

        for alcance in traverse_scope(sentencia):
            for origen in alcance.sources.values():
                if not isinstance(origen, exp.Table):
                    continue
                if (origen.catalog or origen.db.casefold() not in ('', 'dbo')
                        or not isinstance(origen.this, exp.Identifier)
                        or origen.name.casefold() not in TABLAS):
                    raise ErrorConsulta('Usa las tablas o cubos de London Fire Brigade que aparecen en la consola.')
                origen.set('db', exp.to_identifier('dbo'))

        return sentencia.sql(dialect='tsql', comments=False, unsupported_level=ErrorLevel.RAISE)
    except (SqlglotError, RecursionError) as error:
        raise ErrorConsulta('Revisa la sintaxis de la consulta T-SQL e inténtalo de nuevo.') from error


def ejecutar_consulta(consulta, conectar):
    """Ejecuta un SELECT con una conexión nueva y devuelve columnas, filas y truncado."""
    consulta = normalizar_consulta(consulta)
    conexion = None
    etapa = 'conexion'
    try:
        try:
            conexion = conectar()
        except (ValueError, OSError) as error:
            raise ErrorConsulta('No se pudo conectar al datamart. Revisa la configuración de SQL Server.') from error
        conexion.timeout = TIEMPO_LIMITE
        cursor = conexion.cursor()
        etapa = 'permisos'
        cursor.execute("EXECUTE AS USER = 'lfb_lector_consultas' WITH NO REVERT")
        cursor.execute(f'SET ROWCOUNT {MAX_FILAS + 1}; SET ANSI_NULLS ON; SET QUOTED_IDENTIFIER ON')
        etapa = 'consulta'
        cursor.execute('EXEC sys.sp_executesql @stmt = ?', consulta)
        columnas = [columna[0] or f'Columna {i}' for i, columna in enumerate(cursor.description, start=1)]
        filas = cursor.fetchmany(MAX_FILAS + 1)
        return columnas, [tuple(fila) for fila in filas[:MAX_FILAS]], len(filas) > MAX_FILAS
    except pyodbc.Error as error:
        estado = error.args[0] if error.args else ''
        LOG.warning('Consulta del datamart, etapa %s, estado ODBC %s', etapa, estado)
        if estado in ('HYT00', 'HYT01'):
            raise ErrorConsulta('La consulta tardó más de 10 segundos. Reduce el periodo o el número de tablas.') from error
        if etapa == 'conexion' or str(estado).startswith('08'):
            raise ErrorConsulta('El datamart no responde. Inténtalo de nuevo en unos segundos.') from error
        if etapa == 'permisos':
            raise ErrorConsulta('El acceso de solo lectura a SQL todavía no está habilitado.') from error
        if estado in ('42S02', '42S22'):
            raise ErrorConsulta('Revisa los nombres de las tablas y columnas que usaste.') from error
        raise ErrorConsulta('SQL Server rechazó la consulta. Revisa su sintaxis y los tipos de datos.') from error
    finally:
        if conexion is not None:
            conexion.close()
