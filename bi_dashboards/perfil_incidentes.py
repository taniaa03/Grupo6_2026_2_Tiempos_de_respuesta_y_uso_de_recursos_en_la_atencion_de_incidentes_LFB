from collections import Counter
from contextlib import closing
from math import floor, log10
from textwrap import wrap

import plotly.graph_objects as go

from filtro_subgrupo import columna_subgrupo, etiqueta_subgrupo


INMUEBLES = {
    'Dwelling': 'Vivienda',
    'Other Residential': 'Otra residencia',
    'Non Residential': 'No residencial',
    'Outdoor': 'Al aire libre',
    'Outdoor Structure': 'Estructura exterior',
    'Road Vehicle': 'Vehículo de carretera',
    'Rail Vehicle': 'Vehículo ferroviario',
    'Boat': 'Embarcación',
    'Aircraft': 'Aeronave',
    'Desconocido': 'Sin clasificar',
}
COLORES_INMUEBLE = {
    'Dwelling': '#245668',
    'Other Residential': '#963d38',
    'Non Residential': '#894d2b',
    'Outdoor': '#40664e',
    'Outdoor Structure': '#65546f',
    'Road Vehicle': '#4d526f',
    'Rail Vehicle': '#695b42',
    'Boat': '#416565',
    'Aircraft': '#755065',
}
GRUPOS = {
    'Fire': 'Incendios',
    'False Alarm': 'Falsas alarmas',
    'Special Service': 'Servicios especiales',
    'Desconocido': 'Sin clasificar',
}
ALARMAS = {
    'AFA': '#9a581b',
    'False alarm - Good intent': '#245668',
    'False alarm - Malicious': '#a32e2a',
    'Alleged Fire Risk': '#5d6543',
}
ALARMAS_EJE = {
    'AFA': 'AFA',
    'False alarm - Good intent': 'Buena<br>fe',
    'False alarm - Malicious': 'Maliciosa',
    'Alleged Fire Risk': 'Presunto<br>riesgo',
}
GRIS = '#646e69'
ANIO_BASE = 2021
ANIO_FINAL = 2025


def numero(valor, decimales=0):
    return f'{valor:,.{decimales}f}'.translate(str.maketrans(',.', '\u202f,'))


def categoria_alarma(codigo):
    return 'Sin clasificar' if codigo == 'Desconocido' else etiqueta_subgrupo(codigo)


def categoria_inmueble(codigo):
    return INMUEBLES.get(codigo, codigo)


def figura_barras(categorias, etiquetas, unidad, maximo, leyenda=False, vacio='Sin atenciones'):
    figura = go.Figure()
    figura.update_layout(
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f',
        margin=dict(l=10, r=16, t=8, b=42), dragmode=False, barmode='stack',
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
        showlegend=leyenda, legend=dict(orientation='h', x=0, y=1.03, yanchor='bottom'),
    )
    figura.update_xaxes(
        visible=bool(categorias), title_text=unidad, fixedrange=True, automargin=True,
        gridcolor='#e8e5db', zeroline=False, rangemode='tozero', tickformat=',.0f', nticks=5,
    )
    if 0 < maximo < 5:
        figura.update_xaxes(dtick=1)
    figura.update_yaxes(
        visible=bool(categorias), fixedrange=True, automargin=True, showgrid=False,
        categoryorder='array', categoryarray=categorias, autorange='reversed',
        tickvals=categorias, ticktext=['<br>'.join(wrap(etiqueta, width=18)) for etiqueta in etiquetas],
    )
    if not categorias:
        figura.add_annotation(text=vacio, x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False)
    return figura


def mapa_inmuebles(totales, por_grupo):
    if not totales:
        return figura_barras([], [], '', 0)
    categorias = sorted(totales, key=lambda categoria: (-totales[categoria], categoria))
    total = totales.total()
    detalles = []
    for categoria in categorias:
        porcentaje = 100 * totales[categoria] / total
        etiqueta = f'{numero(porcentaje, 1)} %' if porcentaje >= 0.1 else 'Menos de 0,1 %'
        composicion = ''.join(
            f'<br>{GRUPOS.get(grupo, grupo)} · {numero(cantidad)}'
            for grupo, cantidad in por_grupo[categoria].most_common()
        )
        detalles.append((etiqueta, composicion))
    figura = go.Figure(go.Treemap(
        labels=[categoria_inmueble(categoria) for categoria in categorias],
        parents=[''] * len(categorias),
        values=[totales[categoria] for categoria in categorias],
        customdata=detalles,
        marker=dict(
            colors=[COLORES_INMUEBLE.get(categoria, GRIS) for categoria in categorias],
            line=dict(color='#fffdf7', width=2),
        ),
        texttemplate='%{label}<br>%{customdata[0]}',
        hovertemplate='%{label}<br>%{value:,.0f} incidentes · %{customdata[0]}%{customdata[1]}<extra></extra>',
        textfont=dict(color='#fffdf7', size=15),
        tiling=dict(pad=2), pathbar=dict(visible=False), sort=False,
    ))
    figura.update_layout(
        paper_bgcolor='#fffdf7', separators=',\u202f', margin=dict(l=0, r=0, t=4, b=0),
        font=dict(family='Instrument Sans, Arial, sans-serif', color='#293636'),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
        uniformtext=dict(minsize=11, mode='hide'),
    )
    return figura


def comparar_periodos(periodos, atenciones_anuales):
    categorias = sorted(
        set().union(*(atenciones_anuales[periodo] for periodo in periodos)),
        key=lambda categoria: (-sum(atenciones_anuales[periodo][categoria] for periodo in periodos), categoria),
    )
    etiquetas = [categoria_inmueble(categoria) for categoria in categorias]
    maximo = max((max(atenciones_anuales[p].values(), default=0) for p in periodos), default=0)
    figura = figura_barras(categorias, etiquetas, 'Incidentes atendidos', maximo, len(periodos) > 1)
    if not categorias:
        return figura, 'No se registraron atenciones en los años de la comparación.'

    datos = [[atenciones_anuales[periodo][categoria] for categoria in categorias] for periodo in periodos]
    if len(periodos) > 1:
        x, y = [], []
        for categoria, desde, hasta in zip(categorias, *datos):
            x.extend((desde, hasta, None))
            y.extend((categoria, categoria, None))
        figura.add_scatter(
            x=x, y=y, mode='lines', line=dict(color='#a9aa9b', width=2),
            hoverinfo='skip', showlegend=False,
        )
    detalles = [
        '<br>'.join(f'{periodo} · {numero(conteo)} incidentes' for periodo, conteo in zip(periodos, cantidades))
        for cantidades in zip(*datos)
    ]
    marcas = (
        dict(color='#9a581b', size=13, symbol='circle-open', line=dict(width=2)),
        dict(color='#245668', size=8, symbol='diamond'),
    )
    for periodo, cantidades, marca in zip(periodos, datos, marcas):
        figura.add_scatter(
            x=cantidades, y=categorias, text=etiquetas, customdata=detalles,
            mode='markers', name=str(periodo), marker=marca, cliponaxis=False,
            hovertemplate='%{text}<br>%{customdata}<extra></extra>',
        )
    nota = ' · '.join(f'{numero(atenciones_anuales[periodo].total())} en {periodo}' for periodo in periodos)
    return figura, nota


def porcentaje_alarma(porcentaje, decimales=1):
    if porcentaje in (0, 100):
        return f'{numero(porcentaje)} %'
    distancia = min(porcentaje, 100 - porcentaje)
    if distancia < 1:
        decimales = max(decimales, -floor(log10(distancia)))
    return f'{numero(porcentaje, decimales)} %'


def dona_alarmas(alarmas, categorias):
    if not categorias:
        return figura_barras([], [], '', 0, vacio='Sin falsas alarmas')
    total = alarmas.total()
    etiquetas = [categoria_alarma(categoria) for categoria in categorias]
    valores = [alarmas[categoria] for categoria in categorias]
    figura = go.Figure(go.Pie(
        labels=[f'{etiqueta} · {numero(valor)}' for etiqueta, valor in zip(etiquetas, valores)],
        values=valores, hole=0.65, sort=False, direction='clockwise', textinfo='none',
        marker=dict(colors=[ALARMAS.get(categoria, GRIS) for categoria in categorias]),
        customdata=[
            (etiqueta, porcentaje_alarma(100 * valor / total))
            for etiqueta, valor in zip(etiquetas, valores)
        ],
        hovertemplate='%{customdata[0]}<br>%{value:,.0f} falsas alarmas · %{customdata[1]}<extra></extra>',
    ))
    figura.update_layout(
        paper_bgcolor='#fffdf7', separators=',\u202f',
        margin=dict(l=10, r=10, t=8, b=82 if len(categorias) > 2 else 44),
        font=dict(family='Instrument Sans, Arial, sans-serif', color='#293636', size=12),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'), showlegend=True,
        legend=dict(
            orientation='h', x=0.5, xanchor='center', y=-0.03, yanchor='top',
            itemclick=False, itemdoubleclick=False, font=dict(size=11),
        ),
    )
    figura.add_annotation(
        text=f'<b>{numero(total)}</b>', x=0.5, y=0.54, xref='paper', yref='paper', showarrow=False,
        font=dict(size=24),
    )
    figura.add_annotation(
        text='Falsas alarmas', x=0.5, y=0.43, xref='paper', yref='paper', showarrow=False,
        font=dict(size=11, color='#4d605d'),
    )
    return figura


def mapa_alarmas(categorias, alarmas_por_inmueble, alarmas_por_categoria):
    if not categorias:
        return figura_barras([], [], '', 0, vacio='Sin falsas alarmas')
    inmuebles = sorted(alarmas_por_inmueble, key=lambda inmueble: (-alarmas_por_inmueble[inmueble], inmueble))
    porcentajes, detalles = [], []
    for inmueble in inmuebles:
        total = alarmas_por_inmueble[inmueble]
        fila, detalle = [], []
        for categoria in categorias:
            cantidad = alarmas_por_categoria[categoria][inmueble]
            proporcion = 100 * cantidad / total
            fila.append(proporcion)
            detalle.append((cantidad, total, porcentaje_alarma(proporcion)))
        porcentajes.append(fila)
        detalles.append(detalle)

    etiquetas_y = [categoria_inmueble(inmueble) for inmueble in inmuebles]
    etiquetas_x = [categoria_alarma(categoria) for categoria in categorias]
    marcas = [0, 25, 50, 75, 100]
    figura = go.Figure(go.Heatmap(
        x=etiquetas_x, y=etiquetas_y, z=porcentajes, zmin=0, zmax=100,
        colorscale=[(0, '#f6f0df'), (0.55, '#9ab9ae'), (1, '#245668')],
        xgap=2, ygap=2, customdata=detalles,
        hovertemplate=(
            '%{y} · %{x}<br>%{customdata[0]:,.0f} de %{customdata[1]:,.0f} falsas alarmas'
            '<br>%{customdata[2]} del inmueble<extra></extra>'
        ),
        colorbar=dict(
            title=dict(text='Proporción por inmueble', side='top'),
            orientation='h', x=0.5, y=-0.15, yanchor='top', len=0.85,
            thickness=9, outlinewidth=0, tickfont=dict(size=10),
            tickvals=marcas, ticktext=[f'{marca} %' for marca in marcas],
        ),
    ))
    figura.update_layout(
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f',
        margin=dict(l=100, r=12, t=12, b=130, autoexpand=False), dragmode=False,
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'), showlegend=False,
    )
    figura.update_xaxes(
        tickvals=etiquetas_x, ticktext=[
            ALARMAS_EJE.get(categoria, '<br>'.join(wrap(etiqueta, width=10)))
            for categoria, etiqueta in zip(categorias, etiquetas_x)
        ], tickfont=dict(size=9), fixedrange=True, showgrid=False, zeroline=False,
    )
    figura.update_yaxes(
        tickvals=etiquetas_y, ticktext=['<br>'.join(wrap(etiqueta, width=14)) for etiqueta in etiquetas_y],
        tickfont=dict(size=11), categoryorder='array', categoryarray=etiquetas_y, autorange='reversed',
        fixedrange=True, showgrid=False, zeroline=False,
    )
    for inmueble, fila in zip(etiquetas_y, porcentajes):
        for categoria, porcentaje in zip(etiquetas_x, fila):
            figura.add_annotation(
                x=categoria, y=inmueble, text=porcentaje_alarma(porcentaje, 0), showarrow=False,
                font=dict(size=10, color='#ffffff' if porcentaje >= 82.1 else '#000000'),
            )
    figura.add_annotation(
        text='0 % = sin casos de ese subtipo', x=0.5, y=-0.15, xref='paper', yref='paper',
        yanchor='top', yshift=-56, showarrow=False, font=dict(size=11, color='#52615c'),
    )
    return figura


def nota_principal(totales, etiqueta, unidad, nota_vacia):
    if not totales:
        return nota_vacia
    categoria, maximo = totales.most_common(1)[0]
    singular = {'atenciones': 'atención', 'falsas alarmas': 'falsa alarma'}
    cantidad = f'{numero(maximo)} {singular[unidad] if maximo == 1 else unidad}'
    if len(totales) == 1:
        return f'{etiqueta(categoria)} registra {cantidad}.'
    total = totales.total()
    empatadas = sum(conteo == maximo for conteo in totales.values())
    if empatadas > 1:
        return f'{numero(empatadas)} categorías comparten el primer lugar con {cantidad} cada una.'
    return (
        f'{etiqueta(categoria)} reúne {numero(maximo)} de {numero(total)} {unidad} '
        f'({numero(100 * maximo / total, 1)} %).'
    )


def perfil_incidentes(conectar, anio, borough, grupo, subgrupo='todos'):
    anio_seleccionado = None if anio == 'todos' else int(anio)
    anio_comparado = ANIO_FINAL if anio_seleccionado is None else anio_seleccionado
    periodos = (ANIO_BASE,) if anio_comparado == ANIO_BASE else (ANIO_BASE, anio_comparado)
    condiciones = []
    parametros = []
    if anio_seleccionado is not None:
        marcas = ', '.join('?' for _ in periodos)
        condiciones.append(f'i.AnioFuente IN ({marcas})')
        parametros.extend(periodos)
    for campo, valor in (
        ('g.BoroughNombre', borough), ('t.Grupo', grupo),
        (columna_subgrupo(grupo), subgrupo),
    ):
        if valor != 'todos':
            condiciones.append(f'{campo} = ?')
            parametros.append(valor)
    filtro = 'WHERE ' + ' AND '.join(condiciones) if condiciones else ''
    consulta = f'''
        SELECT i.AnioFuente, p.Categoria, t.Grupo, t.Clasificacion, COUNT_BIG(*) AS Atenciones
        FROM dbo.FactIncidente AS i
        INNER JOIN dbo.DimGeografia AS g ON g.GeografiaKey = i.GeografiaKey
        INNER JOIN dbo.DimTipoIncidente AS t ON t.TipoIncidenteKey = i.TipoIncidenteKey
        INNER JOIN dbo.DimTipoPropiedad AS p ON p.TipoPropiedadKey = i.TipoPropiedadKey
        {filtro}
        GROUP BY i.AnioFuente, p.Categoria, t.Grupo, t.Clasificacion;
    '''
    with closing(conectar()) as conn:
        filas = conn.cursor().execute(consulta, *parametros).fetchall()

    atenciones = Counter()
    atenciones_por_grupo = {}
    atenciones_anuales = {periodo: Counter() for periodo in periodos}
    alarmas = Counter()
    alarmas_por_inmueble = Counter()
    alarmas_por_categoria = {}
    for anio_fuente, inmueble, tipo, clasificacion, cantidad in filas:
        inmueble = inmueble or 'Desconocido'
        if anio_fuente in atenciones_anuales:
            atenciones_anuales[anio_fuente][inmueble] += cantidad
        if anio_seleccionado is not None and anio_fuente != anio_seleccionado:
            continue
        atenciones[inmueble] += cantidad
        atenciones_por_grupo.setdefault(inmueble, Counter())[tipo or 'Desconocido'] += cantidad
        if tipo == 'False Alarm':
            clasificacion = clasificacion or 'Desconocido'
            alarmas[clasificacion] += cantidad
            alarmas_por_inmueble[inmueble] += cantidad
            alarmas_por_categoria.setdefault(clasificacion, Counter())[inmueble] += cantidad

    fig_atenciones = mapa_inmuebles(atenciones, atenciones_por_grupo)
    nota_atenciones = nota_principal(
        atenciones, categoria_inmueble, 'atenciones',
        'No se registraron atenciones para los filtros elegidos.',
    )
    fig_evolucion, nota_evolucion = comparar_periodos(periodos, atenciones_anuales)

    categorias = sorted(alarmas, key=lambda categoria: (-alarmas[categoria], categoria))
    sin_alarmas = 'No se registraron falsas alarmas para los filtros elegidos.'
    if grupo not in ('todos', 'False Alarm'):
        sin_alarmas = 'El tipo de incidente seleccionado excluye las falsas alarmas.'
    fig_tipo = dona_alarmas(alarmas, categorias)
    nota_tipo = nota_principal(alarmas, categoria_alarma, 'falsas alarmas', sin_alarmas)

    fig_inmueble = mapa_alarmas(categorias, alarmas_por_inmueble, alarmas_por_categoria)
    nota_inmueble = '' if categorias else sin_alarmas
    return (
        fig_atenciones, nota_atenciones, fig_evolucion, nota_evolucion,
        fig_tipo, nota_tipo, fig_inmueble, nota_inmueble,
    )
