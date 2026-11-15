from decimal import Decimal
from textwrap import wrap

from dash import html
import pandas as pd
import plotly.graph_objects as go


TIPOS = {
    'Fire': ('Incendio', '#a32e2a'),
    'False Alarm': ('Falsa alarma', '#9a581b'),
    'Special Service': ('Servicio especial', '#245668'),
}
MESES = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')
PENIQUE = Decimal('0.01')


def importe(valor):
    if pd.isna(valor):
        return None
    return Decimal(str(valor)).quantize(PENIQUE)


def numero(valor, decimales=0):
    return f'{valor:,.{decimales}f}'.translate(str.maketrans(',.', '\u202f,'))


def libras(valor, decimales=0):
    return f'£{numero(valor, decimales)}'


def estilo(figura, leyenda=False):
    figura.update_layout(
        margin=dict(l=10, r=12, t=22, b=12),
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f',
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
        legend=dict(orientation='h', x=0, y=1.04, yanchor='bottom'), showlegend=leyenda,
    )
    figura.update_xaxes(gridcolor='#e8e5db', zeroline=False, automargin=True)
    figura.update_yaxes(gridcolor='#e8e5db', zeroline=False, automargin=True)
    return figura


def sin_datos(mensaje):
    figura = estilo(go.Figure())
    figura.add_annotation(text=mensaje, x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False)
    figura.update_xaxes(visible=False)
    figura.update_yaxes(visible=False)
    return figura


def costo_mensual(incidentes):
    meses = incidentes.loc[incidentes['Mes'].between(1, 12)]
    resumen = meses.groupby(['Anio', 'Mes', 'Grupo'], as_index=False)['Costo'].sum(min_count=1)
    if not resumen['Costo'].notna().any():
        return sin_datos('Sin costos mensuales para esta selección')

    resumen['Fecha'] = pd.to_datetime({'year': resumen['Anio'], 'month': resumen['Mes'], 'day': 1})
    fechas = pd.date_range(resumen['Fecha'].min(), resumen['Fecha'].max(), freq='MS')
    figura = go.Figure()
    for grupo, (etiqueta, color) in TIPOS.items():
        serie = resumen.loc[resumen['Grupo'].eq(grupo)].set_index('Fecha')['Costo'].reindex(fechas)
        if serie.notna().any():
            figura.add_scatter(
                x=fechas, y=serie.astype(float), name=etiqueta, mode='lines+markers', connectgaps=False,
                marker=dict(color=color, size=5), line=dict(color=color, width=2.3),
                hovertemplate='%{x|%m/%Y}<br>£%{y:,.2f}<extra>%{fullData.name}</extra>',
            )

    paso = 12 if len(fechas) > 12 else 2
    ticks = fechas[::paso]
    etiquetas = [str(d.year) if len(fechas) > 12 else MESES[d.month - 1] for d in ticks]
    figura.update_xaxes(tickvals=ticks, ticktext=etiquetas)
    figura.update_yaxes(title_text='Libras esterlinas', tickformat=',.0f', nticks=4, rangemode='tozero')
    return estilo(figura, leyenda=True)


def costo_municipal(incidentes):
    nombres = incidentes['Borough'].fillna('').str.strip().str.casefold()
    zonas = incidentes.loc[~nombres.isin(['', 'desconocido'])].groupby('Borough', as_index=False)
    resumen = zonas['Costo'].sum(min_count=1).merge(zonas['Incidentes'].sum(), on='Borough')
    resumen = resumen.dropna(subset=['Costo'])
    if resumen.empty:
        return sin_datos('Sin costos por municipio para esta selección')

    resumen['Valor'] = resumen['Costo'].astype(float)
    resumen = resumen.nlargest(7, 'Valor').sort_values('Valor')
    orden = resumen['Borough'].str.title().tolist()
    etiquetas = ['<br>'.join(wrap(zona, width=14)) for zona in orden]
    figura = go.Figure(go.Bar(
        x=resumen['Valor'], y=orden, customdata=resumen['Incidentes'], orientation='h', marker_color='#9a581b',
        hovertemplate='%{y}<br>£%{x:,.2f}<br>%{customdata:,.0f} incidentes<extra></extra>',
    ))
    figura.update_xaxes(title_text='Libras esterlinas', tickformat=',.0f', rangemode='tozero', nticks=4)
    figura.update_yaxes(categoryorder='array', categoryarray=orden, showgrid=False, tickvals=orden, ticktext=etiquetas)
    return estilo(figura)


def tabla_costos(incidentes):
    grupos = incidentes.groupby('Grupo')
    resumen = grupos['Costo'].sum(min_count=1).to_frame().join(grupos['Incidentes'].sum())
    tiene_conteo = 'ConCostoNocional' in incidentes.columns
    if tiene_conteo:
        resumen = resumen.join(grupos['ConCostoNocional'].sum())
    total = resumen['Costo'].sum(min_count=1)

    filas = []
    for grupo, fila in resumen.iterrows():
        costo = fila['Costo']
        recuento = fila['ConCostoNocional'] if tiene_conteo else fila['Incidentes']
        promedio = costo / Decimal(int(recuento)) if recuento and pd.notna(costo) else None
        participacion = 100 * costo / total if pd.notna(costo) and pd.notna(total) and total else None
        filas.append(html.Tr([
            html.Th(TIPOS[grupo][0], scope='row'),
            html.Td(libras(costo, 2) if pd.notna(costo) else 'Sin dato'),
            html.Td(numero(recuento)),
            html.Td(libras(promedio, 2) if promedio is not None else 'Sin dato'),
            html.Td(f'{numero(participacion, 1)} %' if participacion is not None else '—'),
        ]))

    encabezados = ('Tipo de incidente', 'Costo nocional', 'Con costo informado' if tiene_conteo else 'Incidentes',
                   'Costo por registro con dato' if tiene_conteo else 'Costo ÷ incidentes', 'Participación')
    tabla = html.Table([
        html.Caption('Costo nocional por tipo de incidente'),
        html.Thead(html.Tr([html.Th(etiqueta, scope='col') for etiqueta in encabezados])),
        html.Tbody(filas),
    ])
    return html.Div(tabla, className='tabla-contenedor tabla-costos', role='region', tabIndex=0,
                    **{'aria-label': 'Comparación de costos por tipo de incidente'})


def analizar_costos(meses: pd.DataFrame):
    if 'Nivel' in meses.columns:
        meses = meses.loc[meses['Nivel'].eq('mes')]
    incidentes = meses.loc[meses['Grupo'].isin(TIPOS)].copy()
    incidentes['Costo'] = incidentes['CostoNocionalGBP'].map(importe)
    if not incidentes['Costo'].notna().any():
        vacio = sin_datos('Sin costos para esta selección')
        return vacio, vacio, html.P('Sin costos informados.', className='nota'), 'Valores estimados en GBP.'

    nota = 'Costo nocional: estimación de recursos publicada por LFB en libras esterlinas.'
    if 'ConCostoNocional' not in incidentes.columns:
        nota += ' Costo medio = costo ÷ incidentes del mismo tipo.'
    return costo_mensual(incidentes), costo_municipal(incidentes), tabla_costos(incidentes), nota
