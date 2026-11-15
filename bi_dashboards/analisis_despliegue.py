from collections import defaultdict
from textwrap import wrap

from dash import html
import plotly.graph_objects as go

from filtro_subgrupo import columna_subgrupo


TIPOS = {
    'Fire': 'Incendios',
    'False Alarm': 'Falsas alarmas',
    'Special Service': 'Servicios especiales',
}
ORIGENES = {1: ('Estación propia', '#245668'), 2: ('Otra estación', '#9a581b')}
MEDIDAS = [('Hasta la salida', '#245668'), ('Trayecto', '#9a581b'), ('Hasta la llegada', '#a32e2a')]


def numero(valor, decimales=0):
    return f'{valor:,.{decimales}f}'.translate(str.maketrans(',.', '\u202f,'))


def figura_base(filas, mensaje):
    figura = go.Figure()
    figura.update_layout(
        margin=dict(l=10, r=14, t=36, b=45), paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7',
        separators=',\u202f', dragmode=False, font=dict(family='Instrument Sans, Arial, sans-serif', color='#293636', size=12),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
        legend=dict(orientation='h', y=1.03, yanchor='bottom', x=0, xanchor='left'),
    )
    figura.update_xaxes(visible=bool(filas), fixedrange=True, rangemode='tozero', gridcolor='#e8e5db',
                        automargin=True, zeroline=False)
    figura.update_yaxes(visible=bool(filas), fixedrange=True, automargin=True, showgrid=False)
    if not filas:
        figura.add_annotation(text=mensaje, x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False)
    return figura


def analizar_despliegue(conectar, anio, borough, grupo, subgrupo='todos'):
    condiciones = []
    parametros = []
    uniones = []
    for campo, valor, union in (
        ('m.AnioFuente', anio, ''),
        ('g.BoroughNombre', borough, 'INNER JOIN dbo.DimGeografia AS g ON g.GeografiaKey = m.GeografiaKey'),
        ('t.Grupo', grupo, 'INNER JOIN dbo.DimTipoIncidente AS t ON t.TipoIncidenteKey = m.TipoIncidenteKey'),
        (columna_subgrupo(grupo), subgrupo, ''),
    ):
        if valor != 'todos':
            condiciones.append(f'{campo} = ?')
            parametros.append(valor)
            uniones.append(union)
    filtro = 'WHERE ' + ' AND '.join(condiciones) if condiciones else ''
    sql = f'''
        WITH base AS (
            SELECT m.TipoIncidenteKey, m.EstacionKey, m.OrigenDespliegueKey, m.TieneIncidente,
                   m.SalidaSeg, m.ViajeSeg, m.LlegadaSeg,
                   CASE WHEN m.SalidaSeg >= 0 AND m.ViajeSeg >= 0 AND m.LlegadaSeg >= 0
                             AND CONVERT(bigint, m.SalidaSeg) + m.ViajeSeg = m.LlegadaSeg
                        THEN 1 ELSE 0 END AS Comparable
            FROM dbo.FactMovilizacion AS m
            {' '.join(uniones)}
            {filtro}
        ), resumen AS (
            SELECT TipoIncidenteKey, EstacionKey, OrigenDespliegueKey, TieneIncidente,
                   COUNT_BIG(*) AS Filas,
                   COUNT_BIG(CASE WHEN Comparable = 1 THEN 1 END) AS Comparables,
                   SUM(CASE WHEN Comparable = 1 THEN CONVERT(bigint, SalidaSeg) ELSE 0 END) AS Salida,
                   SUM(CASE WHEN Comparable = 1 THEN CONVERT(bigint, ViajeSeg) ELSE 0 END) AS Viaje,
                   SUM(CASE WHEN Comparable = 1 THEN CONVERT(bigint, LlegadaSeg) ELSE 0 END) AS Llegada
            FROM base
            GROUP BY TipoIncidenteKey, EstacionKey, OrigenDespliegueKey, TieneIncidente
        )
        SELECT t.Grupo, r.EstacionKey, e.Codigo, e.Nombre, r.OrigenDespliegueKey, r.TieneIncidente,
               r.Filas, r.Comparables, r.Salida, r.Viaje, r.Llegada
        FROM resumen AS r
        INNER JOIN dbo.DimTipoIncidente AS t ON t.TipoIncidenteKey = r.TipoIncidenteKey
        INNER JOIN dbo.DimEstacion AS e ON e.EstacionKey = r.EstacionKey;
    '''
    conn = conectar()
    try:
        filas = conn.cursor().execute(sql, *parametros).fetchall()
    finally:
        conn.close()

    estaciones = defaultdict(lambda: {1: 0, 2: 0})
    tiempos = defaultdict(lambda: {'total': 0, 'comparables': 0, 'sumas': [0, 0, 0]})
    total = enlazadas = 0
    for tipo, estacion_key, codigo, nombre, origen, tiene_incidente, cantidad, n, salida, viaje, llegada in filas:
        total += cantidad
        enlazadas += cantidad if tiene_incidente else 0
        if estacion_key > 0 and origen in ORIGENES:
            estaciones[codigo, nombre][origen] += cantidad
        if tipo in TIPOS:
            tiempos[tipo]['total'] += cantidad
            tiempos[tipo]['comparables'] += n
            for i, suma in enumerate((salida, viaje, llegada)):
                tiempos[tipo]['sumas'][i] += suma

    ranking = sorted(estaciones, key=lambda estacion: (-sum(estaciones[estacion].values()), estacion[0]))[:8]
    grafico_estaciones = figura_base(ranking, 'Sin estación y origen registrados')
    for origen, (etiqueta, color) in ORIGENES.items():
        if ranking:
            grafico_estaciones.add_bar(
                x=[estaciones[estacion][origen] for estacion in ranking],
                y=[codigo for codigo, _ in ranking], customdata=[nombre for _, nombre in ranking],
                name=etiqueta, orientation='h', marker_color=color,
                hovertemplate='%{customdata} · %{y}<br>%{x:,.0f} movilizaciones<extra>%{fullData.name}</extra>',
            )
    grafico_estaciones.update_layout(barmode='stack')
    grafico_estaciones.update_xaxes(title_text='Movilizaciones con origen registrado', nticks=5, tickformat=',.0f')
    if ranking and sum(estaciones[ranking[0]].values()) < 5:
        grafico_estaciones.update_xaxes(dtick=1)
    grafico_estaciones.update_yaxes(
        categoryorder='array', categoryarray=[codigo for codigo, _ in ranking], autorange='reversed',
        tickvals=[codigo for codigo, _ in ranking],
        ticktext=['<br>'.join(wrap(nombre, width=16, max_lines=2, placeholder='…')) for _, nombre in ranking],
    )

    tipos_mostrados = [tipo for tipo in TIPOS if tiempos[tipo]['total']]
    promedios = {tipo: [suma / tiempos[tipo]['comparables'] for suma in tiempos[tipo]['sumas']]
                 for tipo in tipos_mostrados if tiempos[tipo]['comparables']}
    grafico_tiempos = figura_base(promedios, 'Sin tiempos comparables por tipo')
    for i, (etiqueta, color) in enumerate(MEDIDAS):
        if promedios:
            grafico_tiempos.add_bar(
                x=[promedios[tipo][i] for tipo in promedios], y=list(promedios),
                customdata=[(TIPOS[tipo], tiempos[tipo]['comparables']) for tipo in promedios],
                name=etiqueta, marker_color=color, orientation='h',
                hovertemplate='%{customdata[0]}<br>%{x:,.1f} s de media<br>%{customdata[1]:,.0f} movilizaciones<extra>%{fullData.name}</extra>',
            )
    grafico_tiempos.update_layout(barmode='group')
    grafico_tiempos.update_xaxes(title_text='Tiempo promedio (s)', nticks=5, tickformat=',~f')
    grafico_tiempos.update_yaxes(
        categoryorder='array', categoryarray=list(promedios), autorange='reversed',
        tickvals=list(promedios), ticktext=['<br>'.join(wrap(TIPOS[tipo], width=14)) for tipo in promedios],
    )

    if tipos_mostrados:
        columnas = ('Tipo de incidente', 'Movilizaciones', 'Con tiempos válidos',
                    'Hasta la salida (s)', 'Trayecto (s)', 'Hasta la llegada (s)')
        tabla = html.Div(html.Table([
            html.Thead(html.Tr([html.Th(columna, scope='col') for columna in columnas])),
            html.Tbody([html.Tr([
                html.Th(TIPOS[tipo], scope='row'), html.Td(numero(tiempos[tipo]['total'])),
                html.Td(numero(tiempos[tipo]['comparables'])), *[
                    html.Td(numero(valor, 1) if valor is not None else 'Sin dato')
                    for valor in promedios.get(tipo, [None, None, None])
                ],
            ]) for tipo in tipos_mostrados]),
        ]), className='tabla-contenedor', tabIndex=0, role='region', **{'aria-label': 'Tiempos promedio por tipo de incidente'})
    else:
        tabla = html.P('Sin movilizaciones de un tipo identificado en esta selección.', className='nota')

    comparables = sum(tiempos[tipo]['comparables'] for tipo in tipos_mostrados)
    resumen = (
        f'{numero(enlazadas)} de {numero(total)} movilizaciones tienen un incidente asociado. '
        f'Los promedios usan {numero(comparables)} de tipo conocido cuya espera antes de salir y trayecto '
        'suman el tiempo hasta la llegada.'
        if total else 'No hay movilizaciones para los filtros elegidos.'
    )
    return grafico_estaciones, grafico_tiempos, tabla, resumen
