import plotly.graph_objects as go

from filtro_subgrupo import columna_subgrupo


DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')
DIAS_EJE = ('Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom')
CREMA = '#fffdf7'
VERDE = '#245668'


def actividad_horaria(conectar, anio, borough, grupo, subgrupo='todos'):
    condiciones = []
    valores = []
    for campo, valor in (
        ('i.AnioFuente', anio), ('g.BoroughNombre', borough), ('t.Grupo', grupo),
        (columna_subgrupo(grupo), subgrupo),
    ):
        if valor != 'todos':
            condiciones.append(f'{campo} = ?')
            valores.append(valor)

    filtro = 'WHERE ' + ' AND '.join(condiciones) if condiciones else ''
    sql = f'''
        SELECT f.DiaSemana, h.Hora, COUNT_BIG(*) AS Incidentes
        FROM dbo.FactIncidente AS i
        INNER JOIN dbo.DimFecha AS f ON f.FechaKey = i.FechaKey
        INNER JOIN dbo.DimHora AS h ON h.HoraKey = i.HoraKey
        INNER JOIN dbo.DimGeografia AS g ON g.GeografiaKey = i.GeografiaKey
        INNER JOIN dbo.DimTipoIncidente AS t ON t.TipoIncidenteKey = i.TipoIncidenteKey
        {filtro}
        GROUP BY f.DiaSemana, h.Hora;
    '''

    conn = conectar()
    try:
        filas = conn.cursor().execute(sql, *valores).fetchall()
    finally:
        conn.close()

    matriz = [[0] * 24 for _ in DIAS]
    sin_horario = 0
    for dia, hora, incidentes in filas:
        if dia is None or hora is None or not (1 <= dia <= 7 and 0 <= hora <= 23):
            sin_horario += incidentes
        else:
            matriz[dia - 1][hora] = incidentes

    figura = go.Figure()
    figura.update_layout(
        paper_bgcolor=CREMA, plot_bgcolor=CREMA, separators=',\u202f',
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
        margin=dict(l=45, r=14, t=12, b=132, autoexpand=False), dragmode=False,
    )
    observaciones = sum(map(sum, matriz))
    if not observaciones:
        mensaje = ('Sin día u hora de llamada para los incidentes seleccionados.'
                   if sin_horario else 'Sin incidentes en la selección.')
        figura.add_annotation(text='Sin observaciones', x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False)
        figura.update_xaxes(visible=False)
        figura.update_yaxes(visible=False)
        return figura, mensaje

    maximo = max(map(max, matriz))
    y_leyenda = -0.24
    figura.add_heatmap(
        z=matriz, x=list(range(24)), y=list(range(1, 8)),
        zmin=0, zmax=maximo, colorscale=[(0, '#eef3eb'), (0.5, '#8cb2af'), (1, VERDE)],
        customdata=[[f'{dia.capitalize()} · {hora:02d}:00 a {hora:02d}:59' for hora in range(24)] for dia in DIAS],
        hovertemplate='%{customdata}<br>%{z:,.0f} incidentes<extra></extra>',
        xgap=1, ygap=1,
        colorbar=dict(
            title=dict(text='Incidentes por franja', side='top'),
            orientation='h', x=0.5, y=y_leyenda, yanchor='top', lenmode='pixels', len=198,
            thickness=9, outlinewidth=0, tickformat=',.0f',
            tickvals=sorted({0, maximo // 2, maximo}),
        ),
    )
    figura.add_annotation(
        text='0 = sin incidentes registrados en esa franja',
        x=0.5, y=y_leyenda, xref='paper', yref='paper', yanchor='top', yshift=-57,
        showarrow=False, font=dict(size=11, color='#52615c'),
    )
    marcas = list(range(0, 24, 4))
    figura.update_xaxes(tickvals=marcas, ticktext=[f'{hora:02d}:00' for hora in marcas],
                        range=[-0.5, 23.5], title_text='Hora de llamada', fixedrange=True)
    figura.update_yaxes(tickvals=list(range(1, 8)), ticktext=DIAS_EJE,
                        range=[7.5, 0.5], fixedrange=True)

    picos = [(dia, hora) for dia, conteos in enumerate(matriz)
             for hora, incidentes in enumerate(conteos) if incidentes == maximo]
    cantidad = f'{maximo:,}'.replace(',', '\u202f')
    unidad = 'incidente' if maximo == 1 else 'incidentes'
    if len(picos) == 1:
        dia, hora = picos[0]
        nombre_dia = DIAS[dia] if DIAS[dia].endswith('s') else DIAS[dia] + 's'
        resumen = f'Pico los {nombre_dia}, {hora:02d}:00–{hora:02d}:59 · {cantidad} {unidad}.'
    else:
        resumen = f'Pico de {cantidad} {unidad} en {len(picos)} franjas.'
    if sin_horario:
        cantidad_sin_hora = f'{sin_horario:,}'.replace(',', '\u202f')
        resumen += f' Sin día u hora de llamada · {cantidad_sin_hora}.'
    return figura, resumen
