from contextlib import closing
from datetime import date
from textwrap import wrap

from dash import html
import plotly.graph_objects as go


ANIOS = range(2021, 2026)
MESES = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')
PETROLEO = '#245668'
ROJO = '#a32e2a'


def numero(valor, decimales=0):
    return f'{valor:,.{decimales}f}'.translate(str.maketrans(',.', '\u202f,'))


def figura_base():
    figura = go.Figure()
    figura.update_layout(
        margin=dict(l=12, r=16, t=10, b=36),
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f', showlegend=False,
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
    )
    figura.update_xaxes(gridcolor='#e8e5db', zeroline=False, fixedrange=True, automargin=True)
    figura.update_yaxes(gridcolor='#e8e5db', zeroline=False, fixedrange=True, automargin=True)
    return figura


def sin_registros(mensaje, rotulo):
    figuras = (figura_base(), figura_base())
    for figura in figuras:
        figura.add_annotation(text=rotulo, x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False)
        figura.update_xaxes(visible=False)
        figura.update_yaxes(visible=False)
    return (*figuras, None, mensaje)


def tabla_prevencion(zonas):
    filas = []
    for _, municipio, _, _, alarmas, costo, minutos in zonas:
        filas.append(html.Tr([
            html.Th(municipio.title(), scope='row'),
            html.Td(numero(alarmas)),
            html.Td(f'£{numero(costo)}' if costo is not None else 'Sin dato'),
            html.Td(numero(minutos) if minutos is not None else 'Sin dato'),
        ]))
    return html.Div(html.Table([
        html.Caption('Falsas alarmas automáticas en inmuebles no residenciales'),
        html.Thead(html.Tr([html.Th(texto, scope='col') for texto in (
            'Municipio', 'Falsas alarmas', 'Costo nocional (GBP)', 'Minutos de autobomba redondeados',
        )])),
        html.Tbody(filas),
    ]), className='tabla-contenedor tabla-municipal', role='region', tabIndex=0,
        **{'aria-label': 'Atenciones y recursos por municipio'})


def analizar_prevencion(conectar, anio, borough, grupo, subgrupo='todos'):
    if grupo not in ('todos', 'False Alarm') or subgrupo not in ('todos', 'AFA'):
        return sin_registros('Este análisis cubre las falsas alarmas automáticas en inmuebles no residenciales.',
                             'Sin alarmas automáticas en la selección')

    condiciones = [
        "t.Grupo = N'False Alarm'",
        "t.Clasificacion = N'AFA'",
        "p.Categoria = N'Non Residential'",
        'g.GeografiaKey <> 0',
        "LTRIM(RTRIM(g.BoroughNombre)) NOT IN (N'', N'Desconocido')",
    ]
    parametros = []
    for columna, valor in (('i.AnioFuente', anio), ('g.BoroughNombre', borough)):
        if valor != 'todos':
            condiciones.append(f'{columna} = ?')
            parametros.append(valor)
    filtro = ' AND '.join(condiciones)
    consulta = f"""
        SELECT GROUPING(g.BoroughNombre) AS EsSerie, g.BoroughNombre, i.AnioFuente, f.Mes,
               COUNT_BIG(*) AS Atenciones, SUM(i.CostoNocionalGBP) AS CostoNocional,
               SUM(CAST(i.MinutosBombaRedondeados AS bigint)) AS MinutosBomba
        FROM dbo.FactIncidente AS i
        INNER JOIN dbo.DimTipoIncidente AS t ON t.TipoIncidenteKey = i.TipoIncidenteKey
        INNER JOIN dbo.DimTipoPropiedad AS p ON p.TipoPropiedadKey = i.TipoPropiedadKey
        INNER JOIN dbo.DimGeografia AS g ON g.GeografiaKey = i.GeografiaKey
        INNER JOIN dbo.DimFecha AS f ON f.FechaKey = i.FechaKey
        WHERE {filtro}
        GROUP BY GROUPING SETS ((g.BoroughNombre), (i.AnioFuente, f.Mes));
    """
    with closing(conectar()) as conexion:
        filas = conexion.cursor().execute(consulta, *parametros).fetchall()

    zonas = sorted((fila for fila in filas if not fila[0]), key=lambda fila: (-fila[4], fila[1]))[:8]
    if not zonas:
        return sin_registros('No se registraron falsas alarmas automáticas en inmuebles no residenciales.',
                             'Sin falsas alarmas automáticas')

    zonas_grafico = list(reversed(zonas))
    nombres = [fila[1].title() for fila in zonas_grafico]
    recuentos = [fila[4] for fila in zonas_grafico]
    figura_zonas = figura_base()
    figura_zonas.add_scatter(
        x=[x for recuento in recuentos for x in (0, recuento, None)],
        y=[y for nombre in nombres for y in (nombre, nombre, None)],
        mode='lines', line=dict(color='#9bb1aa', width=1.5), hoverinfo='skip',
    )
    figura_zonas.add_scatter(
        x=recuentos, y=nombres, mode='markers+text',
        marker=dict(size=10, color=[PETROLEO] * (len(nombres) - 1) + [ROJO],
                    line=dict(color='#fffdf7', width=1)),
        text=[numero(recuento) for recuento in recuentos],
        textposition='middle right', textfont=dict(size=11), cliponaxis=False,
        customdata=[
            [f'£{numero(costo)}' if costo is not None else 'Sin dato',
             f'{numero(minutos)} min' if minutos is not None else 'Sin dato']
            for _, _, _, _, _, costo, minutos in zonas_grafico
        ],
        hovertemplate=('<b>%{y}</b><br>%{text} falsas alarmas automáticas'
                       '<br>Costo nocional · %{customdata[0]}'
                       '<br>Tiempo de autobomba · %{customdata[1]}<extra></extra>'),
    )
    figura_zonas.update_xaxes(title_text='Falsas alarmas automáticas', range=[0, recuentos[-1] * 1.35],
                              tickformat=',.0f', nticks=4)
    if zonas[0][4] < 5:
        figura_zonas.update_xaxes(dtick=1)
    figura_zonas.update_yaxes(
        showgrid=False, categoryorder='array', categoryarray=nombres, tickvals=nombres,
        ticktext=['<br>'.join(wrap(nombre, width=18)) for nombre in nombres],
    )

    serie = {(fila[2], fila[3]): fila[4] for fila in filas if fila[0] and fila[3] is not None}
    fechas = [date(a, mes, 1) for a in (ANIOS if anio == 'todos' else [int(anio)]) for mes in range(1, 13)]
    fechas_eje = fechas[::12] if anio == 'todos' else fechas[::2]
    recuentos_mensuales = [serie.get((fecha.year, fecha.month), 0) for fecha in fechas]
    figura_tendencia = figura_base()
    figura_tendencia.add_scatter(
        x=fechas, y=recuentos_mensuales,
        mode='lines+markers', line=dict(color=PETROLEO, width=2.2),
        marker=dict(size=4 if anio == 'todos' else 6,
                    color=[PETROLEO if recuento else '#fffdf7' for recuento in recuentos_mensuales],
                    line=dict(color=PETROLEO, width=1)),
        customdata=[f'{MESES[fecha.month - 1]} {fecha.year}' for fecha in fechas],
        hovertemplate='%{customdata}<br>%{y:,.0f} falsas alarmas automáticas<extra></extra>',
    )
    figura_tendencia.update_xaxes(
        tickvals=fechas_eje, tickangle=0,
        ticktext=[str(fecha.year) if anio == 'todos' else MESES[fecha.month - 1] for fecha in fechas_eje],
    )
    figura_tendencia.update_yaxes(title_text='Falsas alarmas automáticas', rangemode='tozero',
                                  tickformat=',.0f', nticks=5)
    if max(serie.values(), default=0) < 5:
        figura_tendencia.update_yaxes(dtick=1)

    _, municipio, _, _, alarmas, costo, _ = zonas[0]
    resumen = f'{municipio.title()} registra {numero(alarmas)} falsas alarmas automáticas'
    if costo is not None:
        resumen += f' · £{numero(costo)} de costo nocional'
    resumen += '.'
    if anio == 'todos':
        antes = sum(serie.get((2024, mes), 0) for mes in range(1, 10))
        despues = sum(serie.get((2025, mes), 0) for mes in range(1, 10))
        if antes or despues:
            territorio = 'Londres' if borough == 'todos' else municipio.title()
            resumen += (f' Entre enero y septiembre, en {territorio} hubo {numero(antes)} en 2024 '
                        f'y {numero(despues)} en 2025.')

    return figura_zonas, figura_tendencia, tabla_prevencion(zonas), resumen
