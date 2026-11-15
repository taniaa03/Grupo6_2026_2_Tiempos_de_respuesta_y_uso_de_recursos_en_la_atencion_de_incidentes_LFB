import json
import logging
import os
from functools import lru_cache
from math import isfinite
from pathlib import Path
from textwrap import wrap
from threading import Lock
import warnings

import dash
from dash import Input, Output, State, ctx, dcc, html
from flask import send_file
import pandas as pd
import plotly.graph_objects as go
import pyodbc

from consulta_sql import ErrorConsulta, ejecutar_consulta
from actividad_horaria import actividad_horaria
from analisis_costos import analizar_costos
from analisis_despliegue import analizar_despliegue
from analisis_llegada import distribucion_llegada
from analisis_municipal import MINIMO_TIEMPOS, analizar_municipios
from analisis_prevencion import analizar_prevencion
from estaciones_mapa import estaciones_por_municipio
from perfil_incidentes import perfil_incidentes
from filtro_subgrupo import agregados_subgrupo, etiqueta_subgrupo, subgrupos_registrados


ANIOS = list(range(2021, 2026))
MESES = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')
GRUPOS = {'Fire': 'Incendio', 'False Alarm': 'Falsa alarma', 'Special Service': 'Servicio especial'}
COLORES = {'Incendio': '#a32e2a', 'Falsa alarma': '#9a581b', 'Servicio especial': '#245668'}
OBJETIVOS = (
    ('atenciones', 'Atenciones', 'municipios'),
    ('respuesta', 'Respuesta', 'respuesta'),
    ('recursos', 'Recursos', 'recursos'),
    ('falsas', 'Falsas alarmas', 'falsas'),
)
MOTIVOS_DEMORA = {
    '3': 'Simulacro en curso',
    '5': 'Dirección incompleta o errónea',
    '6': 'Falla del vehículo o equipo',
    '7': 'Demora al llegar por otra causa',
    '8': 'Medidas para reducir la velocidad',
    '9': 'Tráfico u obras viales',
    '10': 'Condiciones meteorológicas',
    '11': 'Problema de móvil o radio',
    '13': 'Servicio fuera de la estación',
}
MEDIDAS_MAPA = {
    'estaciones': ('Estaciones con movilizaciones', 'Estaciones', 0, '', '', 'Sin estaciones',
                   'Estaciones que enviaron recursos a incidentes del municipio.'),
    'incidentes': ('Incidentes', 'Incidentes', 0, '', '', 'Sin incidentes', ''),
    'movilizaciones': ('Movilizaciones enlazadas', 'Movilizaciones', 0, '', '', 'Sin movilizaciones', ''),
    'tiempo': ('Tiempo medio de primera llegada', 'Primera llegada (min)', 2, '', ' min', '',
               f'Desde la movilización · Mín. {MINIMO_TIEMPOS} tiempos por municipio'),
    'segunda': ('Tiempo medio de segunda llegada', 'Segunda llegada (min)', 2, '', ' min', '',
                f'Desde la movilización · Mín. {MINIMO_TIEMPOS} tiempos por municipio'),
    'bombas': ('Participaciones de autobomba', 'Participaciones de autobomba', 0, '', '', 'Sin participaciones',
               'Autobombas asistentes sumadas por incidente.'),
    'horas': ('Horas de autobomba', 'Horas de autobomba', 1, '', ' h', '', 'A partir de los minutos redondeados de la fuente.'),
    'intensidad': ('Movilizaciones por incidente', 'Movilizaciones por incidente', 2, '', '', '',
                   'Movilizaciones enlazadas ÷ incidentes.'),
    'costo': ('Costo nocional', 'Costo nocional (GBP)', 0, '£', '', 'Costo nocional cero',
              'Estimación sumada una vez por incidente.'),
    'alarmas': ('Falsas alarmas', 'Falsas alarmas', 0, '', '', 'Sin falsas alarmas', ''),
    'tasa_alarmas': ('Porcentaje de falsas alarmas', 'Falsas alarmas (%)', 1, '', ' %', '',
                     'Falsas alarmas como porcentaje de los incidentes filtrados.'),
}
REPO = os.getenv('LFB_CODE_URL', 'https://github.com/taniaa03/London')
DATOS = os.getenv('LFB_DATAMART_URL', 'datos')
FUENTES = 'https://fonts.googleapis.com/css2?family=DM+Serif+Text&family=Instrument+Sans:wght@400;500;600;650;700&display=swap'
LOG = logging.getLogger(__name__)
RAIZ = Path(__file__).resolve().parent.parent
LECTURA_DATAMART = Lock()


def get_datamart_connection():
    servidor = os.getenv('LFB_SQL_SERVER', r'.\SQLEXPRESS')
    base = os.getenv('LFB_SQL_DATABASE', 'LondonFireBrigadeDM')
    usuario = os.getenv('LFB_SQL_USER')
    clave = os.getenv('LFB_SQL_PASSWORD')
    driver = os.getenv('LFB_SQL_DRIVER', 'ODBC Driver 18 for SQL Server')
    conexion = f'DRIVER={{{driver}}};SERVER={servidor};DATABASE={base};Encrypt=yes;'
    if usuario and clave:
        # ODBC usa llaves para proteger los caracteres especiales de la contraseña.
        conexion += 'UID={' + usuario.replace('}', '}}') + '};'
        conexion += 'PWD={' + clave.replace('}', '}}') + '};'
        conexion += 'TrustServerCertificate=no;'
    elif usuario or clave:
        raise ValueError('Configure el usuario y la contraseña de SQL Server juntos.')
    else:
        conexion += 'Trusted_Connection=yes;TrustServerCertificate=yes;'
    conn = pyodbc.connect(conexion, timeout=8)
    conn.timeout = 60
    return conn


def load_data():
    with LECTURA_DATAMART:
        return cargar_cubos()


@lru_cache(maxsize=1)
def cargar_cubos():
    conn = get_datamart_connection()
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy connectable')
            incidentes = pd.read_sql('SELECT * FROM dbo.CuboIncidentes', conn)
            movilizaciones = pd.read_sql('SELECT * FROM dbo.CuboMovilizaciones', conn)
    finally:
        conn.close()
    if incidentes.empty or movilizaciones.empty:
        raise ValueError('Las vistas de resumen no tienen filas. Ejecute primero la carga y vistas_resumen.sql.')
    return incidentes, movilizaciones


@lru_cache(maxsize=1)
def cargar_subgrupos():
    return subgrupos_registrados(get_datamart_connection)


def subgrupo_valido(grupo, subgrupo):
    if not subgrupo or subgrupo == 'todos' or grupo not in GRUPOS:
        return 'todos'
    return subgrupo if subgrupo in cargar_subgrupos().get(grupo, ()) else 'todos'


@lru_cache(maxsize=20)
def cargar_cubos_subgrupo(grupo, subgrupo):
    return agregados_subgrupo(get_datamart_connection, grupo, subgrupo)


def cargar_datos(grupo, subgrupo):
    if subgrupo == 'todos':
        return load_data()
    with LECTURA_DATAMART:
        return cargar_cubos_subgrupo(grupo, subgrupo)


def filtrar(datos, anio, borough, grupo):
    if anio != 'todos':
        datos = datos[datos['Anio'].eq(anio)]
    if borough != 'todos':
        datos = datos[datos['Borough'].eq(borough)]
    if grupo != 'todos':
        datos = datos[datos['Grupo'].eq(grupo)]
    return datos


def numero(valor, decimales=0):
    if valor is None or not isfinite(valor):
        return 'Sin dato'
    return f'{valor:,.{decimales}f}'.translate(str.maketrans(',.', '\u202f,'))


def categoria_registrada(valores):
    return valores.notna() & ~valores.str.strip().str.casefold().isin(('', 'desconocido'))


def indicador(etiqueta, valor, detalle):
    return html.Div([
        html.Span(etiqueta, className='indicador-etiqueta'),
        html.Strong(valor, className='indicador-valor'),
        html.Span(detalle, className='indicador-detalle'),
    ], className='indicador')


def variacion_anual(valor, anterior, anio, detalle):
    if anterior <= 0:
        return detalle
    variacion = 100 * (valor - anterior) / anterior
    signo = '+' if variacion > 0 else ''
    return f'{signo}{numero(variacion, 1)} % frente a {anio - 1}'


def graficar_vacio(mensaje='Sin observaciones para esta selección'):
    figura = go.Figure()
    figura.add_annotation(text=mensaje, x=0.5, y=0.5, showarrow=False)
    figura.update_xaxes(visible=False)
    figura.update_yaxes(visible=False)
    return estilo(figura)


def estilo(figura, leyenda=False):
    figura.update_layout(
        margin=dict(l=12, r=16, t=10, b=40),
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f',
        showlegend=leyenda, legend=dict(orientation='h', x=0, y=1.035, yanchor='bottom', tracegroupgap=4),
        legend_title_text='',
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
    )
    figura.update_xaxes(title_text='', gridcolor='#e8e5db', zeroline=False, automargin=True)
    figura.update_yaxes(title_text='', gridcolor='#e8e5db', zeroline=False, automargin=True)
    return figura


def eje_mes(figura, datos):
    fechas = datos['Fecha'].dropna().drop_duplicates().sort_values()
    if len(fechas) > 12:
        marcas = fechas[fechas.dt.month.eq(1)]
        etiquetas = [str(fecha.year) for fecha in marcas]
    else:
        marcas = fechas.iloc[::2]
        etiquetas = [MESES[fecha.month - 1] for fecha in marcas]
    figura.update_xaxes(
        tickvals=marcas.tolist(), ticktext=etiquetas, tickangle=0,
    )


def demanda_mensual(incidentes):
    meses = incidentes[incidentes['Mes'].between(1, 12) & incidentes['Grupo'].isin(GRUPOS)]
    if meses.empty:
        return graficar_vacio()
    meses = meses.groupby(['Anio', 'Mes', 'Grupo'], as_index=False)['Incidentes'].sum()
    meses['Fecha'] = pd.to_datetime({'year': meses['Anio'], 'month': meses['Mes'], 'day': 1})
    meses['Tipo'] = meses['Grupo'].replace(GRUPOS)
    figura = go.Figure()
    for tipo, color in COLORES.items():
        serie = meses[meses['Tipo'].eq(tipo)].sort_values('Fecha')
        if not serie.empty:
            figura.add_scatter(
                x=serie['Fecha'].tolist(), y=serie['Incidentes'].tolist(), mode='lines+markers',
                name=tipo, line=dict(color=color, width=2.4), marker_size=5,
                hovertemplate='%{x|%m/%Y}<br>%{y:,.0f} incidentes<extra>%{fullData.name}</extra>',
            )
    eje_mes(figura, meses)
    estilo(figura, leyenda=True)
    figura.update_layout(hovermode='x unified')
    figura.update_yaxes(title_text='Incidentes', tickformat=',.0f', nticks=5, rangemode='tozero')
    return figura


def evolucion_anual(incidentes, movilizaciones, anio):
    figura = go.Figure()
    for datos, medida, activo, inactivo in (
        (incidentes, 'Incidentes', '#a32e2a', '#c68c80'),
        (movilizaciones, 'Movilizaciones', '#245668', '#83a4aa'),
    ):
        totales = datos.groupby('Anio')[medida].sum().reindex(ANIOS, fill_value=0)
        figura.add_bar(
            x=[str(a) for a in ANIOS], y=totales.tolist(), name=medida,
            marker_color=[activo if anio in ('todos', a) else inactivo for a in ANIOS],
            hovertemplate='%{y:,.0f} %{fullData.name}<extra></extra>',
        )
    estilo(figura, leyenda=True)
    figura.update_layout(barmode='group', bargap=0.32, hovermode='x unified', clickmode='event', dragmode=False)
    figura.update_xaxes(type='category', fixedrange=True)
    figura.update_yaxes(title_text='Cantidad', tickformat=',.0f', rangemode='tozero', nticks=5, fixedrange=True)
    return figura


def tiempos_mensuales(incidentes):
    meses = incidentes[incidentes['Mes'].between(1, 12)]
    if meses.empty:
        return graficar_vacio()
    campos = ['SumaPrimeraLlegada', 'SumaSegundaLlegada', 'ConPrimeraLlegada', 'ConSegundaLlegada']
    meses = meses.groupby(['Anio', 'Mes'], as_index=False)[campos].sum()
    meses['Fecha'] = pd.to_datetime({'year': meses['Anio'], 'month': meses['Mes'], 'day': 1})
    figura = go.Figure()
    series = [
        ('Primera llegada', 'SumaPrimeraLlegada', 'ConPrimeraLlegada', '#a32e2a', 'solid'),
        ('Segunda llegada', 'SumaSegundaLlegada', 'ConSegundaLlegada', '#245668', 'dash'),
    ]
    for etiqueta, suma, cuenta, color, trazo in series:
        minutos = meses[suma].div(meses[cuenta].where(meses[cuenta].ne(0))).div(60)
        figura.add_scatter(
            x=meses['Fecha'], y=minutos, customdata=meses[cuenta], name=etiqueta,
            mode='lines+markers', line=dict(color=color, width=2.4, dash=trazo), marker_size=5,
            hovertemplate='%{x|%m/%Y}<br>%{y:.2f} min de media<br>%{customdata:,.0f} arribo(s) registrados<extra>%{fullData.name}</extra>',
        )
    if not meses[['ConPrimeraLlegada', 'ConSegundaLlegada']].to_numpy().any():
        return graficar_vacio('Sin tiempos registrados para esta selección')
    eje_mes(figura, meses)
    estilo(figura, leyenda=True)
    figura.update_layout(hovermode='x unified')
    figura.update_yaxes(title_text='Tiempo de llegada (min)', tickformat='.1f', rangemode='tozero', nticks=5)
    return figura


def barras(datos, categoria, medida, color, unidad, eje):
    if datos.empty:
        return graficar_vacio()
    datos = datos.sort_values(medida)
    figura = go.Figure(go.Bar(
        x=datos[medida], y=datos[categoria], orientation='h',
        marker_color=['#83a6ab'] * (len(datos) - 1) + [color],
        text=[numero(valor) for valor in datos[medida]], textposition='outside',
        textfont=dict(color='#293636', size=11), cliponaxis=False,
        hovertemplate=f'%{{y}}<br>%{{x:,.0f}}{unidad}<extra></extra>',
    ))
    estilo(figura)
    figura.update_layout(bargap=0.31, margin_r=38)
    figura.update_yaxes(
        tickvals=datos[categoria].tolist(),
        ticktext=['<br>'.join(wrap(etiqueta, width=18)) for etiqueta in datos[categoria]],
        showgrid=False,
    )
    figura.update_xaxes(title_text=eje, tickformat=',.0f', range=[0, max(datos[medida]) * 1.14 or 1], nticks=4)
    return figura


def grafico(id_grafico):
    clase = 'grafico serie' if id_grafico in ('demanda-mensual', 'tiempos-mensuales') else 'grafico'
    return html.Div(dcc.Graph(
        id=id_grafico, style={'height': '100%'}, responsive=True, figure=graficar_vacio('Cargando datos…'),
        config={'displayModeBar': False, 'scrollZoom': False},
    ), className=clase)


def tabla_anual(incidentes, movilizaciones):
    demanda = incidentes.groupby('Anio')[['Incidentes', 'FalsasAlarmas']].sum()
    recursos = movilizaciones.groupby('Anio')[['Movilizaciones', 'SinIncidente']].sum()
    resumen = demanda.join(recursos, how='outer').fillna(0).sort_index()
    if resumen.empty:
        return html.P('Sin registros para estos filtros.', className='nota')
    return html.Div(html.Table([
        html.Thead(html.Tr([html.Th(t, scope='col') for t in (
            'Año', 'Incidentes', 'Falsas alarmas', 'Movilizaciones', 'Sin incidente asociado',
        )])),
        html.Tbody([html.Tr([
            html.Th(str(anio), scope='row'),
            *[html.Td(numero(valor)) for valor in fila],
        ]) for anio, fila in resumen.iterrows()]),
    ]), className='tabla-contenedor', tabIndex=0, role='region', **{'aria-label': 'Recuentos por año'})


def indicadores_recursos(meses, movilizaciones):
    bombas = meses['Bombas'].sum(min_count=1)
    minutos = meses['MinutosBomba'].sum(min_count=1)
    costo = meses['CostoNocionalGBP'].sum(min_count=1)
    incidentes = meses['Incidentes'].sum()
    vinculadas = movilizaciones['Movilizaciones'].sum() - movilizaciones['SinIncidente'].sum()
    intensidad = vinculadas / incidentes if incidentes else None
    return [
        indicador('Participaciones de autobomba', numero(bombas), 'Suma por incidente'),
        indicador('Horas de autobomba', numero(minutos / 60), 'A partir de los minutos publicados'),
        indicador('Costo nocional', f'£{numero(costo)}' if pd.notna(costo) else 'Sin dato', 'Valor estimado en GBP'),
        indicador('Movilizaciones por incidente', numero(intensidad, 2), 'Movilizaciones enlazadas ÷ incidentes'),
    ]


def horas_mensuales(meses):
    base = meses[meses['Mes'].between(1, 12) & meses['Grupo'].isin(GRUPOS)]
    datos = base.groupby(['Anio', 'Mes', 'Grupo'], as_index=False)['MinutosBomba'].sum(min_count=1)
    datos = datos.dropna(subset=['MinutosBomba'])
    if datos.empty:
        return graficar_vacio()
    datos['Fecha'] = pd.to_datetime({'year': datos['Anio'], 'month': datos['Mes'], 'day': 1})
    datos['Tipo'] = datos['Grupo'].map(GRUPOS)
    datos['Horas'] = datos['MinutosBomba'] / 60
    figura = go.Figure()
    for tipo, color in COLORES.items():
        serie = datos[datos['Tipo'].eq(tipo)].sort_values('Fecha')
        if not serie.empty:
            figura.add_bar(
                x=serie['Fecha'].tolist(), y=serie['Horas'].tolist(), name=tipo, marker_color=color,
                hovertemplate='%{x|%m/%Y}<br>%{y:,.0f} h<extra>%{fullData.name}</extra>',
            )
    figura.update_layout(barmode='stack')
    eje_mes(figura, datos)
    estilo(figura, leyenda=True)
    figura.update_yaxes(title_text='Horas de autobomba', tickformat=',.0f', nticks=5, rangemode='tozero')
    return figura


def tabla_uso(meses, movilizaciones):
    base = meses[meses['Grupo'].isin(GRUPOS)]
    if base.empty:
        return None
    recursos = base.groupby('Grupo')[['Incidentes', 'Bombas', 'MinutosBomba']].sum(min_count=1)
    envios = movilizaciones.groupby('Grupo')[['Movilizaciones', 'SinIncidente']].sum()
    recursos = recursos.join(envios).fillna({'Movilizaciones': 0, 'SinIncidente': 0})
    filas = []
    for grupo, fila in recursos.sort_values('MinutosBomba', ascending=False).iterrows():
        minutos_por_incidente = fila['MinutosBomba'] / fila['Incidentes'] if fila['Incidentes'] else None
        vinculadas = fila['Movilizaciones'] - fila['SinIncidente']
        filas.append(html.Tr([
            html.Th(GRUPOS[grupo], scope='row'),
            html.Td(numero(fila['Incidentes'])), html.Td(numero(vinculadas)), html.Td(numero(fila['Bombas'])),
            html.Td(numero(fila['MinutosBomba'] / 60)), html.Td(numero(minutos_por_incidente, 1)),
        ]))
    return html.Div(
        html.Table([
            html.Thead(html.Tr([html.Th(titulo, scope='col') for titulo in (
                'Tipo de incidente', 'Incidentes', 'Movilizaciones enlazadas',
                'Participaciones de autobomba', 'Horas de autobomba', 'Minutos por incidente',
            )])),
            html.Tbody(filas),
        ]),
        className='tabla-contenedor', tabIndex=0, role='region',
        **{'aria-label': 'Uso de recursos por tipo de incidente'},
    )


def vista_recurso(titulo, figura, detalle=None):
    encabezado = [html.H3(titulo)]
    if detalle:
        encabezado.append(html.P(detalle, className='nota'))
    return html.Div([
        html.Div(encabezado, className='titulo-grafico'),
        html.Div(dcc.Graph(
            figure=figura, responsive=True, style={'height': '100%'},
            config={'displayModeBar': False, 'scrollZoom': False},
        ), className='grafico grafico-recurso'),
    ], className='recurso')


def contenido_recursos(graficos, tabla=None, nota=None, extras=None):
    secciones = [html.Div([vista_recurso(*grafico) for grafico in graficos], className='recursos recursos-vista')]
    if extras:
        secciones.extend(extras)
    if tabla is not None:
        secciones.append(html.Div(tabla, className='recursos-tabla'))
    if nota:
        secciones.append(html.P(nota, className='nota nota-recursos'))
    return secciones


def panel_recursos():
    return html.Section([
        html.H2('Recursos y costos', className='titulo-seccion'),
        html.Div(id='recursos-indicadores', className='indicadores indicadores-recursos',
                 **{'aria-label': 'Indicadores de recursos'}),
        html.Div([
            html.Label('Vista de recursos', htmlFor='recursos-vista'),
            dcc.Dropdown(
                id='recursos-vista', value='uso', clearable=False, searchable=False,
                options=[
                    {'label': titulo, 'value': clave} for clave, titulo in (
                        ('uso', 'Autobombas y movilizaciones'), ('costos', 'Costo nocional'),
                    )
                ],
            ),
        ], className='selector-medida recurso-medida', role='group', **{'aria-label': 'Vista de recursos'}),
        dcc.Loading(html.Div(id='recursos-contenido', className='recursos-contenido'),
                    delay_show=400, color='#245668'),
    ], id='recursos', className='panel panel-recursos objetivo-panel', role='tabpanel', tabIndex=0,
        **{'data-objetivo': 'recursos', 'aria-labelledby': 'pestana-recursos'})


@lru_cache(maxsize=1)
def limites_londres():
    archivo = Path(__file__).with_name('assets') / 'limites_londres.geojson'
    return json.loads(archivo.read_text(encoding='utf-8'))


def detalle_estaciones(estaciones, borough):
    if borough == 'todos':
        codigos = {fila['codigo'] for filas in estaciones.values() for fila in filas}
        return html.P(f'{numero(len(codigos))} estaciones con movilizaciones en Londres.', className='nota')
    filas = estaciones.get(borough, [])
    if not filas:
        return html.P('Sin movilizaciones con estación registrada para esta selección.', className='nota')
    total = sum(fila['movilizaciones'] for fila in filas)
    tabla = html.Table([
        html.Thead(html.Tr([
            html.Th('Estación', scope='col'), html.Th('Código', scope='col'),
            html.Th('Movilizaciones', scope='col'),
        ])),
        html.Tbody([
            html.Tr([
                html.Th(fila['nombre'], scope='row'), html.Td(fila['codigo']),
                html.Td(numero(fila['movilizaciones'])),
            ]) for fila in filas
        ]),
    ])
    return html.Div([
        html.H3(f'Estaciones que enviaron recursos a {borough.title()}'),
        html.P(f"{numero(len(filas))} estaciones · {numero(total)} movilizaciones", className='nota'),
        html.Div(tabla, className='tabla-contenedor tabla-estaciones', tabIndex=0, role='region',
                 **{'aria-label': 'Estaciones y movilizaciones'}),
    ], className='estaciones-municipio')


def mapa_por_zona(meses, totales, borough, medida, estaciones):
    geometrias = [registro['id'] for registro in limites_londres()['features']]
    campos = ['Incidentes', 'FalsasAlarmas', 'SumaPrimeraLlegada', 'ConPrimeraLlegada',
              'SumaSegundaLlegada', 'ConSegundaLlegada', 'Bombas', 'MinutosBomba', 'CostoNocionalGBP']
    zonas = meses.groupby('Borough')[campos].sum(min_count=1).reindex(geometrias)
    incidentes = zonas['Incidentes'].fillna(0)
    alarmas = zonas['FalsasAlarmas'].fillna(0)
    envios = totales.groupby('Borough')[['Movilizaciones', 'SinIncidente']].sum().reindex(geometrias).fillna(0)
    movilizaciones = envios['Movilizaciones'] - envios['SinIncidente']
    conteos = pd.Series({zona: len(estaciones.get(zona, [])) for zona in geometrias})
    datos = {
        'estaciones': conteos,
        'incidentes': incidentes,
        'movilizaciones': movilizaciones,
        'tiempo': zonas['SumaPrimeraLlegada'].div(
            60 * zonas['ConPrimeraLlegada'].where(zonas['ConPrimeraLlegada'].ge(MINIMO_TIEMPOS))),
        'segunda': zonas['SumaSegundaLlegada'].div(
            60 * zonas['ConSegundaLlegada'].where(zonas['ConSegundaLlegada'].ge(MINIMO_TIEMPOS))),
        'bombas': zonas['Bombas'],
        'horas': zonas['MinutosBomba'] / 60,
        'intensidad': movilizaciones.div(incidentes.where(incidentes.gt(0))),
        'costo': zonas['CostoNocionalGBP'],
        'alarmas': alarmas,
        'tasa_alarmas': 100 * alarmas.div(incidentes.where(incidentes.gt(0))),
    }
    valores = datos[medida].dropna()
    nombre, _, decimales, prefijo, unidad, _, _ = MEDIDAS_MAPA[medida]
    contexto = {'incidentes': incidentes, 'movilizaciones': movilizaciones, 'estaciones': conteos}
    etiquetas = {}
    for zona in geometrias:
        cifra = f'{prefijo}{numero(valores[zona], decimales)}{unidad}' if zona in valores.index else 'Sin dato comparable'
        lineas = [f'<b>{zona.title()}</b>', f'{nombre} · {cifra}']
        for clave, serie in contexto.items():
            if medida != clave:
                lineas.append(f'{MEDIDAS_MAPA[clave][0]} · {numero(serie[zona])}')
        if medida in ('tiempo', 'segunda'):
            muestras = zonas.loc[zona, 'ConPrimeraLlegada' if medida == 'tiempo' else 'ConSegundaLlegada']
            lineas.append(f'{numero(muestras if pd.notna(muestras) else 0)} tiempos informados')
        etiquetas[zona] = '<br>'.join(lineas)
    return dibujar_municipios(valores, borough, medida, etiquetas)


def dibujar_municipios(valores, borough, medida, etiquetas):
    geojson = limites_londres()
    _, escala, decimales, prefijo, unidad, etiqueta_cero, explicacion = MEDIDAS_MAPA[medida]
    figura = go.Figure()
    sin_medida = [zona for zona in etiquetas if zona not in valores.index]
    if sin_medida:
        figura.add_choropleth(
            geojson=geojson, locations=sin_medida, z=[0] * len(sin_medida), showscale=False,
            colorscale=[[0, '#deddd5'], [1, '#deddd5']],
            marker_line_color='#fffdf7', marker_line_width=0.8,
            text=[etiquetas[zona] for zona in sin_medida], hovertemplate='%{text}<extra></extra>',
        )
    variacion = False
    if not valores.empty:
        minimo = 0 if etiqueta_cero else float(valores.min())
        maximo = float(valores.max())
        variacion = minimo < maximo and valores.nunique() > 1
        paleta = ([[0, '#f1e7d3'], [0.45, '#c48c52'], [1, '#754319']]
                  if medida == 'alarmas' else [[0, '#e5ebdf'], [0.45, '#89aaa8'], [1, '#245668']])
        marcas = [minimo, (minimo + maximo) / 2, maximo]
        if etiqueta_cero and not decimales:
            marcas[1] = int(maximo) // 2
        etiquetas_escala = {f'{prefijo}{numero(marca, decimales)}{unidad}': marca for marca in marcas}
        colorbar = dict(orientation='h', x=0.5, xanchor='center', y=0.015, yanchor='bottom',
                        thickness=8, len=0.76, tickmode='array', outlinewidth=0,
                        title=dict(text=escala, side='top', font=dict(size=12)),
                        tickvals=list(etiquetas_escala.values()), ticktext=list(etiquetas_escala))
        figura.add_choropleth(
            geojson=geojson, locations=valores.index.tolist(), z=valores.astype(float).tolist(),
            text=[etiquetas[zona] for zona in valores.index],
            colorscale=paleta if variacion else [[0, '#b7ccc1'], [1, '#b7ccc1']],
            zmin=minimo if variacion else 0, zmax=maximo if variacion else max(1, maximo), showscale=variacion,
            marker_line_color='#fffdf7', marker_line_width=0.8,
            colorbar=colorbar, hovertemplate='%{text}<extra></extra>',
        )
    if borough in etiquetas:
        figura.add_choropleth(
            geojson=geojson, locations=[borough], z=[1], showscale=False,
            colorscale=[[0, 'rgba(163,46,42,0.12)'], [1, 'rgba(163,46,42,0.12)']],
            marker_line_width=2, marker_line_color='#a32e2a', text=[etiquetas[borough]],
            hovertemplate='%{text}<extra></extra>',
        )
    figura.update_geos(fitbounds='geojson', visible=False, projection_type='mercator', bgcolor='#fffdf7',
                       domain=dict(y=[0.16, 1] if variacion else [0, 1]))
    estilo(figura)
    figura.update_layout(margin=dict(l=0, r=0, b=0, t=4), dragmode=False)
    lectura = ''
    if valores.empty:
        lectura = 'Sin datos comparables'
    elif valores.nunique() == 1:
        cifra = f'{prefijo}{numero(valores.iloc[0], decimales)}{unidad}'
        lectura = f'{etiqueta_cero} en los {len(valores)} municipios' if etiqueta_cero and valores.iloc[0] == 0 else (
            f'{escala} · {cifra} en {len(valores)} municipios'
        )
    notas = []
    if variacion and etiqueta_cero:
        notas.append(html.Span([html.Strong('0'), etiqueta_cero.lower()], className='nota mapa-clave'))
    if sin_medida and not valores.empty:
        notas.append(html.Span([html.Span(className='mapa-muestra', **{'aria-hidden': 'true'}), 'Sin dato'],
                               className='nota mapa-clave'))
    if lectura:
        notas.append(html.Span(lectura, className='nota'))
    if explicacion:
        notas.append(html.Span(explicacion, className='nota'))
    if borough in etiquetas:
        cifra = f'{prefijo}{numero(valores[borough], decimales)}{unidad}' if borough in valores.index else 'Sin dato'
        notas.append(html.P(f'{borough.title()} · {escala.lower()} · {cifra}', className='mapa-seleccion'))
    return figura, notas


def concentracion_falsas_alarmas(meses, borough):
    municipios = [feature['id'] for feature in limites_londres()['features']]
    valores = meses.groupby('Borough')['FalsasAlarmas'].sum().reindex(municipios, fill_value=0)
    total = valores.sum()
    etiquetas = {
        zona: f'<b>{zona.title()}</b><br>{numero(conteo)} falsas alarmas'
        for zona, conteo in valores.items()
    }
    figura, notas = dibujar_municipios(valores, borough, 'alarmas', etiquetas)
    if not total:
        return figura, notas, html.P('Sin falsas alarmas localizadas para la selección.', className='nota')

    mayores = valores[valores.gt(0)].sort_values(ascending=False, kind='stable').head(5)
    if borough in valores.index and borough not in mayores.index:
        mayores = pd.concat([mayores, valores.loc[[borough]]])
    filas = [
        html.Tr([
            html.Th(zona.title(), scope='row'),
            html.Td(numero(conteo)),
            html.Td(f'{numero(100 * conteo / total, 1)} %'),
        ], className='municipio-seleccionado' if zona == borough else None)
        for zona, conteo in mayores.items()
    ]
    tabla = html.Table([
        html.Thead(html.Tr([
            html.Th('Municipio', scope='col'),
            html.Th('Falsas alarmas', scope='col'),
            html.Th('Del total localizado', scope='col'),
        ])),
        html.Tbody(filas),
    ])
    detalle = [
        html.P(f'{numero(total)} falsas alarmas localizadas en Londres', className='nota'),
        html.Div(tabla, className='tabla-contenedor tabla-municipal', tabIndex=0, role='region',
                 **{'aria-label': 'Municipios por falsas alarmas'}),
    ]
    return figura, notas, detalle


def panel_consultas():
    url_diagrama = 'diagrama-datamart.png'
    return html.Section([
        html.H2('Consultas SQL', id='sql-titulo'),
        html.Figure([
            html.Img(
                src=url_diagrama, width=2472, height=1592,
                alt='Modelo multidimensional con las tablas de incidentes y movilizaciones y sus dimensiones.',
            ),
            html.Figcaption(html.A(
                'Ver diagrama a tamaño completo', href=url_diagrama,
                target='_blank', rel='noopener', className='enlace-esquema',
            )),
        ], className='sql-diagrama'),
        html.Div([
            html.Div([
                html.Label('Consulta T-SQL', htmlFor='sql-editor'),
                dcc.Textarea(id='sql-editor', value='', spellCheck=False),
                html.Div([
                    html.Button('Ejecutar consulta', id='sql-ejecutar', type='button', className='boton boton-primario'),
                    html.Span('Solo lectura · Se muestran hasta 200 filas', className='nota'),
                ], className='sql-acciones'),
            ], className='sql-formulario'),
            html.Aside([
                html.H3('Esquema del datamart'),
                html.Ul([
                    html.Li(html.Code('dbo.FactIncidente')),
                    html.Li(html.Code('dbo.FactMovilizacion')),
                ], className='sql-objetos'),
                html.Details([
                    html.Summary('Dimensiones y vistas'),
                    html.Ul([
                        html.Li(html.Code(f'dbo.{nombre}')) for nombre in (
                            'DimFecha', 'DimHora', 'DimTipoIncidente', 'DimTipoPropiedad', 'DimGeografia',
                            'DimEstacion', 'DimOrigenDespliegue', 'DimMotivoDemora',
                            'CuboIncidentes', 'CuboMovilizaciones',
                        )
                    ]),
                ], className='sql-esquema'),
                html.A('Diccionario de campos', href='diccionario', className='enlace-esquema'),
            ], className='sql-lateral'),
        ], className='sql-area'),
        html.Div([
            html.H3('Resultados'),
            html.Button('Descargar CSV', id='sql-exportar', disabled=True, type='button', className='boton'),
        ], className='sql-cabecera-resultados'),
        html.P('Aún no se ha ejecutado ninguna consulta.', id='sql-estado', className='sql-estado nota', role='status'),
        html.Div(id='sql-resultados'),
        dcc.Store(id='sql-datos'),
        dcc.Download(id='sql-descarga'),
    ], id='consultas', className='panel panel-sql', **{'aria-labelledby': 'sql-titulo'})


def tabla_sql(columnas, filas):
    return html.Div(
        html.Table([
            html.Thead(html.Tr([html.Th(columna, scope='col') for columna in columnas])),
            html.Tbody([html.Tr([
                html.Td(html.Span('NULL', className='sql-nulo') if valor is None else str(valor))
                for valor in fila
            ]) for fila in filas]),
        ]),
        className='tabla-contenedor sql-tabla', tabIndex=0, role='region',
        **{'aria-label': 'Resultados de la consulta SQL'},
    )


app = dash.Dash(__name__, title='London Fire Brigade | 2021–2025', update_title=None,
                external_stylesheets=[FUENTES])
server = app.server


@server.get('/datos')
def descargar_fuentes():
    return send_file(RAIZ / 'data' / 'README.md', mimetype='text/plain; charset=utf-8',
                     as_attachment=True, download_name='Fuentes_y_datamart.md')


@server.get('/diccionario')
def descargar_diccionario():
    archivo = RAIZ / 'docs' / '04_Diccionario_datos' / 'Diccionario_modelo.md'
    return send_file(archivo, mimetype='text/plain; charset=utf-8', as_attachment=True,
                     download_name='Diccionario_modelo.md')


@server.get('/diagrama-datamart.png')
def mostrar_diagrama_datamart():
    archivo = RAIZ / 'docs' / '05_Modelo_multidimensional' / 'Modelo_multidimensional.png'
    return send_file(archivo, mimetype='image/png')


def panel_atenciones():
    return html.Section([
        html.H2('Atenciones', className='titulo-seccion'),
        html.Div([
            html.Div([
                html.H3('Atenciones por categoría de inmueble'),
                html.P(id='atenciones-inmueble-detalle', className='nota'),
                grafico('atenciones-inmueble'),
            ], className='recurso perfil-inmuebles'),
            html.Div([
                html.H3('Cambio por categoría de inmueble'),
                html.P(id='evolucion-inmueble-detalle', className='nota'),
                grafico('evolucion-inmueble'),
            ], className='recurso perfil-inmuebles'),
        ], className='recursos categorias-inmueble'),
        html.Div([
            html.Div([
                html.H3('Mapa de municipios'),
                html.Div([
                    html.Div([
                        html.Label('Medida del mapa', htmlFor='mapa-medida'),
                        dcc.Dropdown(
                            id='mapa-medida', value='incidentes', clearable=False,
                            options=[
                                {'label': MEDIDAS_MAPA[clave][0], 'value': clave}
                                for clave in ('incidentes', 'estaciones', 'movilizaciones', 'tiempo', 'segunda',
                                              'bombas', 'horas', 'intensidad', 'costo', 'alarmas', 'tasa_alarmas')
                            ],
                        ),
                    ], className='selector-medida', role='group', **{'aria-label': 'Medida del mapa'}),
                    html.Button('Quitar filtro municipal', id='limpiar-mapa', type='button',
                                className='boton boton-ligero', disabled=True),
                ], className='mapa-controles'),
                grafico('mapa-municipios'),
                html.Div(id='mapa-detalle', className='mapa-detalle', role='status'),
                html.A('Límites de Londres (GLA y Ordnance Survey)',
                       href='https://data.london.gov.uk/dataset/london-boroughs-e55pw',
                       className='nota fuente-mapa'),
                html.Div(id='mapa-estaciones', className='subseccion'),
            ], className='recurso mapa-zonas'),
            html.Div([
                html.H3('Incidentes y movilizaciones por año'),
                grafico('evolucion-anual'),
            ], className='recurso recuentos-anuales'),
        ], className='recursos municipios-grid'),
        html.Div([
            html.H3('Incidentes mensuales por tipo'),
            grafico('demanda-mensual'),
        ], id='demanda', className='subseccion'),
        html.Div([
            html.H3('Incidentes por día y hora de llamada'),
            dcc.Loading(grafico('actividad-por-hora'), delay_show=350, color='#245668'),
            html.P(id='horario-detalle', className='nota', role='status'),
        ], className='subseccion'),
    ], id='municipios', className='panel objetivo-panel', role='tabpanel', tabIndex=0,
        **{'data-objetivo': 'atenciones', 'aria-labelledby': 'pestana-atenciones'})


def panel_respuesta():
    return html.Section([
        html.H2('Respuesta y demoras', className='titulo-seccion'),
        html.Div([
            html.Div([
                html.H3('Incidentes y primera llegada por municipio'),
                grafico('volumen-respuesta'),
            ], className='recurso dispersion-zonas'),
            html.Div([
                html.H3('Mayores medias de primera llegada'),
                html.P(id='contexto-municipios', className='nota'),
                html.Div(id='ranking-municipios'),
            ], className='recurso municipal-rango'),
        ], className='recursos municipios-grid'),
        html.Div([
            html.Div([
                html.Div([
                    html.H3('Tiempo medio de llegada por mes'),
                    html.P('Desde la movilización hasta el arribo.', className='nota'),
                ], className='titulo-grafico'),
                grafico('tiempos-mensuales'),
            ], className='recurso'),
            html.Div([
                html.Div([
                    html.H3('Incidentes por intervalo de primera llegada'),
                    html.P(id='llegada-detalle', className='nota', role='status'),
                ], className='titulo-grafico'),
                dcc.Loading(grafico('distribucion-llegada'), delay_show=350, color='#245668'),
            ], className='recurso'),
        ], className='recursos subseccion'),
        dcc.Loading(html.Div(id='demoras-contenido', className='subseccion'), delay_show=400, color='#245668'),
    ], id='respuesta', className='panel objetivo-panel', role='tabpanel', tabIndex=0,
        **{'data-objetivo': 'respuesta', 'aria-labelledby': 'pestana-respuesta'})


def panel_falsas_alarmas():
    return html.Section([
        html.H2('Falsas alarmas', className='titulo-seccion'),
        html.Div([
            html.Div([
                html.H3('Distribución por categoría de alarma'),
                html.P(id='categoria-alarma-detalle', className='nota'),
                grafico('categoria-alarma'),
            ], className='recurso reparto-alarmas'),
            html.Div([
                html.H3('Composición por categoría de inmueble'),
                html.P(id='inmueble-alarma-detalle', className='nota'),
                grafico('inmueble-alarma'),
            ], className='recurso matriz-alarmas'),
        ], className='recursos falsas-composicion'),
        html.Div([
            html.Div([
                html.Div([
                    html.H3('Mapa de falsas alarmas'),
                    html.Button('Quitar filtro municipal', id='limpiar-mapa-falsas', type='button',
                                className='boton boton-ligero', disabled=True),
                ], className='encabezado-mapa-falsas'),
                dcc.Loading(grafico('mapa-falsas-alarmas'), delay_show=350, color='#754319'),
                html.Div(id='mapa-falsas-detalle', className='mapa-detalle', role='status'),
                html.A('Límites de Londres (GLA y Ordnance Survey)',
                       href='https://data.london.gov.uk/dataset/london-boroughs-e55pw',
                       className='nota fuente-mapa'),
            ], className='recurso mapa-zonas'),
            html.Div([
                html.H3('Municipios con más falsas alarmas'),
                html.Div(id='ranking-falsas'),
            ], className='recurso municipal-rango'),
        ], className='recursos falsas-territorio'),
        dcc.Loading(html.Div(id='prevencion-contenido', className='subseccion'), delay_show=400, color='#245668'),
    ], id='falsas', className='panel objetivo-panel', role='tabpanel', tabIndex=0,
        **{'data-objetivo': 'falsas', 'aria-labelledby': 'pestana-falsas'})


app.layout = html.Div([
    html.A('Ir al contenido', href='#contenido', className='saltar'),
    html.Header(html.Div([
        html.Div([html.Span(className='punto', **{'aria-hidden': 'true'}), 'London Fire Brigade'], className='marca'),
        html.Nav([
            html.A('Objetivos', href='#objetivos'),
            html.A('Datos', href='#datos'), html.A('Consultas SQL', href='#consultas', className='nav-sql'),
        ], **{'aria-label': 'Secciones del tablero'}),
    ], className='contenedor barra-superior'), className='masthead'),
    html.Main([
        html.Div([
            html.Div([
                html.P('LONDRES / 2021–2025', className='periodo'),
                html.H1('Respuesta y recursos por zona'),
            ]),
            html.P('Business Intelligence\nUniversidad del Pacífico', className='curso'),
        ], className='cabecera'),
        html.Div([
            html.Fieldset([
                html.Legend('Filtrar el tablero'),
                html.Div([
                    html.Div([html.Label('Año', htmlFor='anio-filter'), dcc.Dropdown(
                        id='anio-filter', options=[{'label': '2021–2025', 'value': 'todos'}] + [
                            {'label': str(anio), 'value': anio} for anio in ANIOS
                        ], value='todos', clearable=False, searchable=False,
                    )], role='group', **{'aria-label': 'Año'}),
                    html.Div([html.Label('Municipio (borough)', htmlFor='borough-filter'), dcc.Dropdown(
                        id='borough-filter', options=[{'label': 'Todos los municipios', 'value': 'todos'}],
                        value='todos', clearable=False, placeholder='Buscar un municipio',
                    )], role='group', **{'aria-label': 'Municipio'}),
                    html.Div([html.Label('Tipo de incidente', htmlFor='grupo-filter'), dcc.Dropdown(
                        id='grupo-filter', options=[{'label': 'Todos los tipos', 'value': 'todos'}] + [
                            {'label': etiqueta, 'value': grupo} for grupo, etiqueta in GRUPOS.items()
                        ], value='todos', clearable=False, searchable=False,
                    )], role='group', **{'aria-label': 'Tipo de incidente'}),
                    html.Div([html.Label('Subgrupo', htmlFor='subgrupo-filter'), dcc.Dropdown(
                        id='subgrupo-filter', options=[{'label': 'Todos los subgrupos', 'value': 'todos'}],
                        value='todos', clearable=False, disabled=True,
                    )], role='group', **{'aria-label': 'Subgrupo'}),
                ], className='filtros'),
            ]),
            html.Div([
                html.P('Cargando cifras…', id='estado', className='estado', role='status'),
                html.Button('Restablecer filtros', id='restablecer-filtros', type='button', className='boton boton-ligero'),
            ], className='estado-filtros'),
        ], className='control-panel'),
        html.Div(id='indicadores', className='indicadores', **{'aria-label': 'Indicadores de la selección'}),
        dcc.Store(id='objetivo-activo', data='atenciones'),
        html.Div([
            html.Button(
                titulo, id=f'pestana-{objetivo}', type='button', role='tab',
                tabIndex=0 if objetivo == 'atenciones' else -1,
                **{'aria-controls': panel, 'aria-selected': 'true' if objetivo == 'atenciones' else 'false'},
            ) for objetivo, titulo, panel in OBJETIVOS
        ], id='objetivos', className='pestanas-objetivos', role='tablist', **{'aria-label': 'Objetivos del análisis'}),
        html.Div([
            panel_atenciones(), panel_respuesta(), panel_recursos(), panel_falsas_alarmas(),
        ], id='paneles-objetivos', **{'data-objetivo-activo': 'atenciones'}),
        panel_consultas(),
        html.Section([
            html.Div([html.H2('Recuentos y fuentes')], className='titulo-seccion'),
            html.Div(id='resumen-anual'),
            html.P('Una movilización corresponde a un recurso enviado. Un incidente puede originar varias movilizaciones. Las movilizaciones sin incidente asociado se incluyen en su año de origen.', className='nota nota-tabla'),
            html.Div([
                html.A('Datos y fuentes', href=DATOS),
                html.A('Diccionario del modelo', href='diccionario'),
                html.A('Repositorio del equipo', href=REPO),
            ], className='enlaces'),
        ], id='datos', className='panel panel-datos'),
    ], className='contenedor contenido', id='contenido', tabIndex=-1),
    html.Footer(html.Div('Datos abiertos de London Fire Brigade · Open Government Licence', className='contenedor')),
])


app.clientside_callback(
    f'''function() {{
        const objetivo = dash_clientside.callback_context.triggered_id.slice('pestana-'.length);
        const atributos = {json.dumps([objetivo for objetivo, _, _ in OBJETIVOS])}.flatMap(tab =>
            tab === objetivo ? ['true', 0] : ['false', -1]);
        return [objetivo, objetivo, ...atributos];
    }}''',
    Output('objetivo-activo', 'data'),
    Output('paneles-objetivos', 'data-objetivo-activo'),
    [salida for objetivo, _, _ in OBJETIVOS for salida in (
        Output(f'pestana-{objetivo}', 'aria-selected'), Output(f'pestana-{objetivo}', 'tabIndex'),
    )],
    [Input(f'pestana-{objetivo}', 'n_clicks') for objetivo, _, _ in OBJETIVOS],
    prevent_initial_call=True,
)


@app.callback(
    Output('anio-filter', 'value'), Output('borough-filter', 'value'), Output('grupo-filter', 'value'),
    Output('evolucion-anual', 'clickData'), Output('volumen-respuesta', 'clickData'), Output('mapa-municipios', 'clickData'),
    Output('mapa-falsas-alarmas', 'clickData'),
    Input('restablecer-filtros', 'n_clicks'), Input('limpiar-mapa', 'n_clicks'), Input('limpiar-mapa-falsas', 'n_clicks'),
    Input('evolucion-anual', 'clickData'),
    Input('volumen-respuesta', 'clickData'), Input('mapa-municipios', 'clickData'),
    Input('mapa-falsas-alarmas', 'clickData'),
    State('anio-filter', 'value'), State('borough-filter', 'value'),
    prevent_initial_call=True,
)
def seleccionar_filtros(_clic, _limpiar, _limpiar_falsas, evento_anio, evento_municipio,
                        evento_mapa, evento_falsas, anio_actual, borough_actual):
    sin_cambio = dash.no_update
    origen = ctx.triggered_id
    if origen == 'restablecer-filtros':
        return 'todos', 'todos', 'todos', None, None, None, None
    if origen in ('limpiar-mapa', 'limpiar-mapa-falsas'):
        return sin_cambio, 'todos', sin_cambio, sin_cambio, None, None, None
    evento = {
        'evolucion-anual': evento_anio, 'volumen-respuesta': evento_municipio, 'mapa-municipios': evento_mapa,
        'mapa-falsas-alarmas': evento_falsas,
    }.get(origen)
    punto = ((evento or {}).get('points') or [{}])[0]
    if origen == 'evolucion-anual':
        anio = punto.get('x')
        if str(anio) in [str(a) for a in ANIOS]:
            valor = 'todos' if int(anio) == anio_actual else int(anio)
            return valor, sin_cambio, sin_cambio, None, sin_cambio, sin_cambio, sin_cambio
    if origen == 'volumen-respuesta':
        datos = punto.get('customdata') or []
        if datos and isinstance(datos[0], str):
            valor = 'todos' if datos[0] == borough_actual else datos[0]
            return sin_cambio, valor, sin_cambio, sin_cambio, None, sin_cambio, sin_cambio
    if origen in ('mapa-municipios', 'mapa-falsas-alarmas'):
        zona = punto.get('location')
        if isinstance(zona, str) and zona:
            valor = 'todos' if zona == borough_actual else zona
            return sin_cambio, valor, sin_cambio, sin_cambio, sin_cambio, None, None
    raise dash.exceptions.PreventUpdate


@app.callback(
    Output('sql-resultados', 'children'), Output('sql-estado', 'children'),
    Output('sql-datos', 'data'), Output('sql-exportar', 'disabled'),
    Input('sql-ejecutar', 'n_clicks'), State('sql-editor', 'value'),
    prevent_initial_call=True,
    running=[
        (Output('sql-ejecutar', 'disabled'), True, False),
        (Output('sql-ejecutar', 'children'), 'Consultando…', 'Ejecutar consulta'),
    ],
)
def consultar_sql(_clic, consulta):
    try:
        columnas, filas, truncado = ejecutar_consulta(consulta or '', get_datamart_connection)
    except ErrorConsulta as error:
        return None, html.Span(str(error), className='sql-error'), None, True
    if not filas:
        return None, 'La consulta se ejecutó y no devolvió filas.', None, True
    valores = [
        [v if v is None or isinstance(v, (str, int, float)) else str(v) for v in fila]
        for fila in filas
    ]
    estado = f'{len(filas)} filas mostradas. Agrega un filtro para reducir el resultado.' if truncado else (
        '1 fila devuelta.' if len(filas) == 1 else f'{len(filas)} filas devueltas.'
    )
    return tabla_sql(columnas, valores), estado, {'columnas': columnas, 'filas': valores}, False


@app.callback(
    Output('sql-descarga', 'data'), Input('sql-exportar', 'n_clicks'), State('sql-datos', 'data'),
    prevent_initial_call=True,
)
def exportar_consulta(_clic, resultado):
    if not resultado:
        raise dash.exceptions.PreventUpdate

    def texto_csv(valor):
        # Una hoja de cálculo puede interpretar ciertos textos como fórmulas.
        if isinstance(valor, str) and valor.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + valor
        return valor

    columnas = [texto_csv(c) for c in resultado['columnas']]
    filas = [[texto_csv(v) for v in fila] for fila in resultado['filas']]
    tabla = pd.DataFrame(filas, columns=columnas)
    return dcc.send_data_frame(tabla.to_csv, 'consulta_lfb.csv', index=False, encoding='utf-8-sig')


@app.callback(
    Output('subgrupo-filter', 'options'), Output('subgrupo-filter', 'value'),
    Output('subgrupo-filter', 'disabled'), Input('grupo-filter', 'value'),
)
def actualizar_subgrupos(grupo):
    opciones = [{'label': 'Todos los subgrupos', 'value': 'todos'}]
    if grupo not in GRUPOS:
        return opciones, 'todos', True
    try:
        disponibles = cargar_subgrupos().get(grupo, ())
    except (pyodbc.Error, ValueError):
        LOG.exception('No se pudieron cargar los subgrupos de incidentes.')
        return opciones, 'todos', True
    opciones.extend({'label': etiqueta_subgrupo(valor), 'value': valor} for valor in disponibles)
    return opciones, 'todos', not disponibles


@app.callback(
    Output('borough-filter', 'options'), Output('grupo-filter', 'options'),
    Output('estado', 'children'), Output('indicadores', 'children'),
    Output('demanda-mensual', 'figure'), Output('evolucion-anual', 'figure'), Output('tiempos-mensuales', 'figure'),
    Output('volumen-respuesta', 'figure'), Output('ranking-municipios', 'children'),
    Output('contexto-municipios', 'children'),
    Output('recursos-indicadores', 'children'), Output('resumen-anual', 'children'),
    Input('anio-filter', 'value'), Input('borough-filter', 'value'), Input('grupo-filter', 'value'),
    Input('subgrupo-filter', 'value'),
)
def update_charts(anio, borough, grupo, subgrupo='todos'):
    try:
        subgrupo = subgrupo_valido(grupo, subgrupo)
        base_incidentes, base_movilizaciones = load_data()
        incidentes, movilizaciones = cargar_datos(grupo, subgrupo)
    except (pyodbc.Error, pd.errors.DatabaseError, ValueError):
        LOG.error('No se pudo consultar el datamart. Revise la conexión y las vistas SQL.')
        vacio = graficar_vacio('Datos no disponibles')
        return (dash.no_update, dash.no_update, 'No se pudo consultar la base. Vuelve a cargar la página para reintentar.',
                [], vacio, vacio, vacio, vacio, None, '', [], None)

    municipios = pd.concat([base_incidentes['Borough'], base_movilizaciones['Borough']]).drop_duplicates()
    municipios = sorted(municipios[categoria_registrada(municipios)])
    opciones_borough = [{'label': 'Todos los municipios', 'value': 'todos'}] + [
        {'label': nombre.title(), 'value': nombre} for nombre in municipios
    ]
    opciones_grupo = [{'label': 'Todos los tipos', 'value': 'todos'}] + [
        {'label': etiqueta, 'value': grupo} for grupo, etiqueta in GRUPOS.items()
    ]

    contexto_inc = filtrar(incidentes, 'todos', borough, grupo)
    contexto_mov = filtrar(movilizaciones, 'todos', borough, grupo)
    contexto_municipios = filtrar(incidentes, anio, 'todos', grupo)
    figura_municipal, tabla_municipal, detalle_municipal = analizar_municipios(
        contexto_municipios[contexto_municipios['Nivel'].eq('mes')], borough,
    )
    anual = evolucion_anual(
        contexto_inc[contexto_inc['Nivel'].eq('mes')], contexto_mov[contexto_mov['Nivel'].eq('total')], anio,
    )
    incidentes = filtrar(contexto_inc, anio, 'todos', 'todos')
    movilizaciones = filtrar(contexto_mov, anio, 'todos', 'todos')
    meses = incidentes[incidentes['Nivel'].eq('mes')]
    totales = movilizaciones[movilizaciones['Nivel'].eq('total')]

    cantidad = meses['Incidentes'].sum()
    alarmas = meses['FalsasAlarmas'].sum()
    con_llegada = meses['ConPrimeraLlegada'].sum()
    promedio = meses['SumaPrimeraLlegada'].sum() / (60 * con_llegada) if con_llegada else None
    porcentaje = 100 * alarmas / cantidad if cantidad else None
    total_mov = totales['Movilizaciones'].sum()
    detalle_incidentes = 'Atenciones registradas'
    detalle_movilizaciones = 'Registros de recursos enviados'
    if anio in ANIOS[1:]:
        inc_anterior = contexto_inc[contexto_inc['Nivel'].eq('mes') & contexto_inc['Anio'].eq(anio - 1)]
        mov_anterior = contexto_mov[contexto_mov['Nivel'].eq('total') & contexto_mov['Anio'].eq(anio - 1)]
        detalle_incidentes = variacion_anual(cantidad, inc_anterior['Incidentes'].sum(), anio, detalle_incidentes)
        detalle_movilizaciones = variacion_anual(
            total_mov, mov_anterior['Movilizaciones'].sum(), anio, detalle_movilizaciones,
        )
    kpis = [
        indicador('Incidentes', numero(cantidad), detalle_incidentes),
        indicador('Movilizaciones', numero(total_mov), detalle_movilizaciones),
        indicador('Falsas alarmas', numero(alarmas), f'{numero(porcentaje, 1)} % de los incidentes' if cantidad else 'Sin incidentes'),
        indicador('Primera llegada', f'{numero(promedio, 2)} min' if con_llegada else 'Sin dato',
            f'{numero(con_llegada)} incidentes con primera llegada registrada'),
    ]
    periodo = '2021–2025' if anio == 'todos' else str(anio)
    zona = 'Todos los municipios' if borough == 'todos' else borough.title()
    tipo = 'Todos los tipos' if grupo == 'todos' else GRUPOS.get(grupo, grupo)
    filtros = f'{periodo} · {zona} · {tipo}'
    if subgrupo != 'todos':
        filtros += f' · {etiqueta_subgrupo(subgrupo)}'
    if not cantidad and not total_mov:
        filtros = 'Sin registros para estos filtros. ' + filtros

    return (opciones_borough, opciones_grupo, filtros, kpis,
            demanda_mensual(meses), anual, tiempos_mensuales(meses), figura_municipal,
            tabla_municipal, detalle_municipal,
            indicadores_recursos(meses, totales), tabla_anual(meses, totales))


@lru_cache(maxsize=96)
def cargar_analisis(analisis, anio, borough, grupo, subgrupo='todos'):
    with LECTURA_DATAMART:
        return analisis(get_datamart_connection, anio, borough, grupo, subgrupo)


@lru_cache(maxsize=24)
def cargar_estaciones(anio, grupo, subgrupo='todos'):
    with LECTURA_DATAMART:
        return estaciones_por_municipio(get_datamart_connection, anio, grupo, subgrupo)


@app.callback(
    Output('mapa-municipios', 'figure'), Output('mapa-detalle', 'children'),
    Output('mapa-estaciones', 'children'), Output('limpiar-mapa', 'disabled'),
    Input('anio-filter', 'value'), Input('borough-filter', 'value'), Input('grupo-filter', 'value'),
    Input('subgrupo-filter', 'value'), Input('mapa-medida', 'value'),
)
def actualizar_mapa(anio, borough, grupo, subgrupo, medida):
    try:
        subgrupo = subgrupo_valido(grupo, subgrupo)
        incidentes, movilizaciones = cargar_datos(grupo, subgrupo)
        contexto = filtrar(incidentes, anio, 'todos', grupo)
        envios = filtrar(movilizaciones, anio, 'todos', grupo)
        estaciones = cargar_estaciones(anio, grupo, subgrupo)
        figura, nota = mapa_por_zona(contexto[contexto['Nivel'].eq('mes')], envios[envios['Nivel'].eq('total')],
                                    borough, medida, estaciones)
        return figura, nota, detalle_estaciones(estaciones, borough), borough == 'todos'
    except (OSError, pyodbc.Error, pd.errors.DatabaseError, ValueError):
        LOG.exception('No se pudo cargar el mapa de municipios.')
        return graficar_vacio('Mapa no disponible'), '', None, borough == 'todos'


@app.callback(
    Output('recursos-contenido', 'children'),
    Input('recursos-vista', 'value'), Input('anio-filter', 'value'),
    Input('borough-filter', 'value'), Input('grupo-filter', 'value'), Input('subgrupo-filter', 'value'),
    Input('objetivo-activo', 'data'),
)
def actualizar_recursos(vista, anio, borough, grupo, subgrupo, objetivo):
    if objetivo != 'recursos':
        raise dash.exceptions.PreventUpdate
    try:
        subgrupo = subgrupo_valido(grupo, subgrupo)
        incidentes, movilizaciones = cargar_datos(grupo, subgrupo)
        incidentes = filtrar(incidentes, anio, borough, grupo)
        meses = incidentes[incidentes['Nivel'].eq('mes')]
        if vista == 'costos':
            mensual, municipal, tabla, nota = analizar_costos(meses)
            return contenido_recursos([
                ('Costo nocional por mes', mensual),
                ('Costo nocional por municipio', municipal),
            ], tabla, nota)

        envio = filtrar(movilizaciones, anio, borough, grupo)
        totales = envio[envio['Nivel'].eq('total')]
        zonas = meses[categoria_registrada(meses['Borough'])]
        zonas = zonas.groupby('Borough', as_index=False)['MinutosBomba'].sum(min_count=1).dropna()
        zonas['Horas'] = zonas['MinutosBomba'] / 60
        zonas['Borough'] = zonas['Borough'].str.title()
        zonas = zonas.nlargest(8, 'Horas')
        estaciones, _, _, _ = cargar_analisis(analizar_despliegue, anio, borough, grupo, subgrupo)
        grafico_estaciones = html.Div(vista_recurso(
            'Estaciones con más movilizaciones', estaciones,
            'Movilizaciones con estación y origen informados.',
        ), className='subseccion')
        return contenido_recursos([
            ('Horas de autobomba por mes y tipo', horas_mensuales(meses)),
            ('Municipios con más horas de autobomba', barras(zonas, 'Borough', 'Horas', '#245668', ' h', 'Horas de autobomba')),
        ], tabla_uso(meses, totales), 'Las horas se calculan a partir de los minutos redondeados en la fuente. '
           'Las participaciones se suman por incidente.', [grafico_estaciones])
    except (pyodbc.Error, pd.errors.DatabaseError, ValueError):
        LOG.exception('No se pudo cargar la vista de recursos %s.', vista)
        return html.P('No se pudo consultar esta vista de recursos.', className='nota', role='status')


@app.callback(
    Output('demoras-contenido', 'children'),
    Input('anio-filter', 'value'), Input('borough-filter', 'value'), Input('grupo-filter', 'value'),
    Input('subgrupo-filter', 'value'), Input('objetivo-activo', 'data'),
)
def actualizar_demoras(anio, borough, grupo, subgrupo, objetivo):
    if objetivo != 'respuesta':
        raise dash.exceptions.PreventUpdate
    try:
        subgrupo = subgrupo_valido(grupo, subgrupo)
        _, movilizaciones = cargar_datos(grupo, subgrupo)
        _, tiempos, tabla, nota = cargar_analisis(analizar_despliegue, anio, borough, grupo, subgrupo)
        envios = filtrar(movilizaciones, anio, borough, grupo)
        motivos = envios[envios['Nivel'].eq('motivo')]
        con_motivo = motivos[categoria_registrada(motivos['Motivo'])]
        reportadas = con_motivo[~con_motivo['MotivoCodigo'].eq('12')]
        total = motivos['Movilizaciones'].sum()
        cobertura = con_motivo['Movilizaciones'].sum()
        con_demora = reportadas['Movilizaciones'].sum()
        ranking = reportadas.groupby(['MotivoCodigo', 'Motivo'], as_index=False)['Movilizaciones'].sum()
        ranking['Motivo'] = ranking['MotivoCodigo'].map(MOTIVOS_DEMORA).fillna(ranking['Motivo'])
        ranking = ranking.nlargest(8, 'Movilizaciones')
        nota_demoras = (
            f'{numero(con_demora)} con causa de demora · {numero(cobertura)} de {numero(total)} con estado de demora informado'
            if total else 'Sin movilizaciones para la selección.'
        )
        return contenido_recursos([
            ('Motivos de demora reportados', barras(ranking, 'Motivo', 'Movilizaciones', '#245668',
                                                    ' movilizaciones', 'Movilizaciones'), nota_demoras),
            ('Tiempos promedio del despliegue', tiempos, 'Salida y llegada medidas desde la movilización.'),
        ], tabla, nota)
    except (pyodbc.Error, pd.errors.DatabaseError, ValueError):
        LOG.exception('No se pudieron consultar las demoras.')
        return html.P('No se pudieron consultar las demoras.', className='nota', role='status')


@app.callback(
    Output('mapa-falsas-alarmas', 'figure'), Output('mapa-falsas-detalle', 'children'),
    Output('ranking-falsas', 'children'), Output('limpiar-mapa-falsas', 'disabled'),
    Output('prevencion-contenido', 'children'),
    Input('anio-filter', 'value'), Input('borough-filter', 'value'), Input('grupo-filter', 'value'),
    Input('subgrupo-filter', 'value'), Input('objetivo-activo', 'data'),
)
def actualizar_prevencion(anio, borough, grupo, subgrupo, objetivo):
    if objetivo != 'falsas':
        raise dash.exceptions.PreventUpdate
    try:
        subgrupo = subgrupo_valido(grupo, subgrupo)
        incidentes, _ = cargar_datos(grupo, subgrupo)
        contexto = filtrar(incidentes, anio, 'todos', grupo)
        figura, notas, ranking = concentracion_falsas_alarmas(contexto[contexto['Nivel'].eq('mes')], borough)
        if grupo not in ('todos', 'False Alarm'):
            notas = [html.Span('El tipo seleccionado excluye las falsas alarmas.', className='nota')]
        zonas, tendencia, tabla, nota = cargar_analisis(analizar_prevencion, anio, borough, grupo, subgrupo)
        contenido = html.P(nota, className='nota') if tabla is None else contenido_recursos([
            ('Alarmas automáticas no residenciales por municipio', zonas),
            ('Alarmas automáticas no residenciales por mes', tendencia),
        ], tabla, nota)
        return figura, notas, ranking, borough == 'todos', contenido
    except (pyodbc.Error, pd.errors.DatabaseError, ValueError):
        LOG.exception('No se pudieron consultar las falsas alarmas.')
        mensaje = 'No se pudieron consultar las falsas alarmas.'
        return graficar_vacio('Mapa no disponible'), None, None, borough == 'todos', html.P(mensaje, className='nota')


@app.callback(
    Output('actividad-por-hora', 'figure'), Output('horario-detalle', 'children'),
    Output('distribucion-llegada', 'figure'), Output('llegada-detalle', 'children'),
    Input('anio-filter', 'value'), Input('borough-filter', 'value'), Input('grupo-filter', 'value'),
    Input('subgrupo-filter', 'value'), Input('objetivo-activo', 'data'),
)
def actualizar_analisis(anio, borough, grupo, subgrupo, objetivo):
    salidas = []
    for tab, analisis in (('atenciones', actividad_horaria), ('respuesta', distribucion_llegada)):
        if objetivo != tab:
            salidas.extend((dash.no_update, dash.no_update))
            continue
        try:
            subgrupo = subgrupo_valido(grupo, subgrupo)
            salidas.extend(cargar_analisis(analisis, anio, borough, grupo, subgrupo))
        except (pyodbc.Error, ValueError):
            LOG.exception('No se pudo consultar %s', analisis.__name__)
            salidas.extend((graficar_vacio('Datos no disponibles'), 'Vuelve a aplicar los filtros para reintentar.'))
    return salidas


@app.callback(
    Output('atenciones-inmueble', 'figure'), Output('atenciones-inmueble-detalle', 'children'),
    Output('evolucion-inmueble', 'figure'), Output('evolucion-inmueble-detalle', 'children'),
    Output('categoria-alarma', 'figure'), Output('categoria-alarma-detalle', 'children'),
    Output('inmueble-alarma', 'figure'), Output('inmueble-alarma-detalle', 'children'),
    Input('anio-filter', 'value'), Input('borough-filter', 'value'), Input('grupo-filter', 'value'),
    Input('subgrupo-filter', 'value'), Input('objetivo-activo', 'data'),
)
def actualizar_perfil(anio, borough, grupo, subgrupo, objetivo):
    if objetivo not in ('atenciones', 'falsas'):
        raise dash.exceptions.PreventUpdate
    try:
        subgrupo = subgrupo_valido(grupo, subgrupo)
        return cargar_analisis(perfil_incidentes, anio, borough, grupo, subgrupo)
    except (pyodbc.Error, ValueError):
        LOG.exception('No se pudo consultar el perfil de incidentes.')
        return (graficar_vacio('Datos no disponibles'), '') * 4


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8050')), debug=False)
