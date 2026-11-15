from html import escape

from dash import html
import pandas as pd
import plotly.graph_objects as go


MINIMO_TIEMPOS = 100
TOTAL_COLUMNAS = ['Incidentes', 'SumaPrimeraLlegada', 'ConPrimeraLlegada']


def numero(valor, decimales=0):
    return f'{valor:,.{decimales}f}'.translate(str.maketrans(',.', '\u202f,'))


def tabla_municipal(zonas, borough):
    mayores = zonas.sort_values(['Minutos', 'Borough'], ascending=[False, True]).head(5)
    seleccionado = zonas[zonas['Borough'].eq(borough)]
    titulo = 'Municipios por tiempo medio de primera llegada'
    if not seleccionado.empty and borough not in mayores['Borough'].values:
        mayores = pd.concat([mayores, seleccionado], ignore_index=True)
        titulo += ' y municipio seleccionado'

    filas = []
    for zona in mayores.itertuples(index=False):
        nombre = zona.Borough.title()
        if zona.Borough == borough:
            nombre = html.Strong(nombre, **{'aria-label': f'{nombre}, seleccionado'})
        filas.append(html.Tr([
            html.Th(nombre, scope='row'),
            html.Td(numero(zona.Incidentes)),
            html.Td(numero(zona.ConPrimeraLlegada)),
            html.Td(numero(zona.Minutos, 2)),
        ], className='municipio-seleccionado' if zona.Borough == borough else None))

    return html.Div(html.Table([
        html.Caption(titulo, className='solo-lectores'),
        html.Thead(html.Tr([html.Th(titulo, scope='col') for titulo in (
            'Municipio', 'Incidentes', 'Con llegada informada', 'Media (min)',
        )])),
        html.Tbody(filas),
    ]), className='tabla-contenedor tabla-municipal', role='region', tabIndex=0,
        **{'aria-label': 'Comparación de municipios por tiempo de primera llegada'})


def analizar_municipios(meses: pd.DataFrame, borough: str):
    nombres = meses['Borough'].fillna('').str.strip().str.casefold()
    conocidos = meses.loc[~nombres.isin(['', 'desconocido'])]
    zonas = conocidos.groupby('Borough', as_index=False)[TOTAL_COLUMNAS].sum()
    elegibles = zonas.loc[zonas['ConPrimeraLlegada'].ge(MINIMO_TIEMPOS)].copy()

    figura = go.Figure()
    figura.update_layout(
        margin=dict(l=8, r=8, t=12, b=12),
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f',
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
        clickmode='event', showlegend=False,
    )
    if elegibles.empty:
        figura.add_annotation(text='Sin municipios comparables', x=0.5, y=0.5,
                              xref='paper', yref='paper', showarrow=False)
        figura.update_xaxes(visible=False)
        figura.update_yaxes(visible=False)
        return (figura, html.P('Sin filas para mostrar.', className='nota'),
                f'Mín. {MINIMO_TIEMPOS} primeras llegadas informadas por municipio.')

    elegibles['Minutos'] = elegibles['SumaPrimeraLlegada'] / (60 * elegibles['ConPrimeraLlegada'])
    ponderado = elegibles['SumaPrimeraLlegada'].sum() / (60 * elegibles['ConPrimeraLlegada'].sum())
    elegibles['Municipio'] = elegibles['Borough'].str.title().map(escape)
    figura.add_hline(y=ponderado, line_width=1.5, line_dash='dot', line_color='#70532d')

    seleccion = elegibles['Borough'].eq(borough)
    for puntos, seleccionado in [(elegibles.loc[~seleccion], False), (elegibles.loc[seleccion], True)]:
        if puntos.empty:
            continue
        figura.add_scatter(
            x=puntos['Incidentes'], y=puntos['Minutos'],
            text=puntos['Municipio'], customdata=puntos[['Borough', 'ConPrimeraLlegada']].values.tolist(),
            mode='markers',
            marker=dict(size=14 if seleccionado else 10, color='#a32e2a' if seleccionado else '#245668',
                        symbol='diamond' if seleccionado else 'circle', line=dict(width=1, color='#fffdf7')),
            hovertemplate='<b>%{text}</b><br>%{x:,.0f} incidentes<br>%{y:.2f} min de primera llegada'
                          '<br>%{customdata[1]:,.0f} llegadas informadas<extra></extra>',
        )

    figura.update_xaxes(title_text='Incidentes', tickformat=',.0f', rangemode='tozero', nticks=5,
                       gridcolor='#e8e5db', zeroline=False, automargin=True)
    figura.update_yaxes(title_text='Primera llegada media (min)', tickformat='.1f', nticks=5,
                       gridcolor='#e8e5db', zeroline=False, automargin=True)

    interpretacion = (f'Línea punteada: media ponderada de {numero(ponderado, 2)} min. '
                      f'Mín. {MINIMO_TIEMPOS} primeras llegadas informadas por municipio.')
    if seleccion.any():
        distrito = elegibles.loc[seleccion].iloc[0]
        interpretacion += (f' {distrito.Borough.title()} registra {numero(distrito.Minutos, 2)} min '
                           f'con {numero(distrito.ConPrimeraLlegada)} tiempos informados.')
    elif borough != 'todos':
        interpretacion += f' {borough.title()} no tiene suficientes primeras llegadas informadas.'

    return figura, tabla_municipal(elegibles, borough), interpretacion
