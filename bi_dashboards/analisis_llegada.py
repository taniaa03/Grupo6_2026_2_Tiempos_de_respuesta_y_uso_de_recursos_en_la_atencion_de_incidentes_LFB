from contextlib import closing

from plotly import graph_objects as go

from filtro_subgrupo import columna_subgrupo


TRAMOS = [
    ('<2', 'Menos de 2 min'),
    ('2–<4', 'De 2 a menos de 4 min'),
    ('4–<6', 'De 4 a menos de 6 min'),
    ('6–<8', 'De 6 a menos de 8 min'),
    ('8–<10', 'De 8 a menos de 10 min'),
    ('10–<15', 'De 10 a menos de 15 min'),
    ('15+', '15 min o más'),
]


def distribucion_llegada(conectar, anio, borough, grupo, subgrupo='todos'):
    condiciones = []
    parametros = []
    for columna, valor in (
        ('i.AnioFuente', anio),
        ('g.BoroughNombre', borough),
        ('t.Grupo', grupo),
        (columna_subgrupo(grupo), subgrupo),
    ):
        if valor != 'todos':
            condiciones.append(f'{columna} = ?')
            parametros.append(valor)

    filtro = 'WHERE ' + ' AND '.join(condiciones) if condiciones else ''
    consulta = f"""
        WITH tiempos AS (
            SELECT CASE
                WHEN i.PrimerArriboSeg IS NULL OR i.PrimerArriboSeg <= 0 THEN -1
                WHEN i.PrimerArriboSeg < 120 THEN 0
                WHEN i.PrimerArriboSeg < 240 THEN 1
                WHEN i.PrimerArriboSeg < 360 THEN 2
                WHEN i.PrimerArriboSeg < 480 THEN 3
                WHEN i.PrimerArriboSeg < 600 THEN 4
                WHEN i.PrimerArriboSeg < 900 THEN 5
                ELSE 6
            END AS Tramo
            FROM dbo.FactIncidente AS i
            INNER JOIN dbo.DimGeografia AS g ON i.GeografiaKey = g.GeografiaKey
            INNER JOIN dbo.DimTipoIncidente AS t ON i.TipoIncidenteKey = t.TipoIncidenteKey
            {filtro}
        )
        SELECT Tramo, COUNT_BIG(*) AS Incidentes
        FROM tiempos
        GROUP BY Tramo;
    """
    with closing(conectar()) as conexion:
        filas = dict(conexion.cursor().execute(consulta, *parametros).fetchall())

    frecuencias = [filas.get(tramo, 0) for tramo in range(len(TRAMOS))]
    validos = sum(frecuencias)
    total = validos + filas.get(-1, 0)
    figura = go.Figure()
    figura.update_layout(
        margin=dict(l=12, r=16, t=10, b=42),
        font=dict(family='Instrument Sans, Arial, sans-serif', size=12, color='#293636'),
        paper_bgcolor='#fffdf7', plot_bgcolor='#fffdf7', separators=',\u202f',
        showlegend=False, bargap=0.25, hoverlabel=dict(bgcolor='#193335', font_color='#ffffff'),
    )
    if not validos:
        figura.update_xaxes(visible=False)
        figura.update_yaxes(visible=False)
        figura.add_annotation(text='Sin tiempos de llegada válidos', x=0.5, y=0.5,
                              xref='paper', yref='paper', showarrow=False)
        if not total:
            return figura, 'Sin incidentes en la selección.'
        cantidad = f'{total:,}'.replace(',', '\u202f')
        return figura, f'0 de {cantidad} incidentes con tiempo válido.'

    porcentajes = [100 * cantidad / validos for cantidad in frecuencias]
    etiquetas = [etiqueta for etiqueta, _ in TRAMOS]
    figura.add_bar(
        x=etiquetas,
        y=porcentajes,
        marker_color=['#245668'] * (len(TRAMOS) - 1) + ['#a32e2a'],
        customdata=[
            [descripcion, f'{cantidad:,}'.replace(',', '\u202f')]
            for cantidad, (_, descripcion) in zip(frecuencias, TRAMOS)
        ],
        hovertemplate='%{customdata[0]}<br>%{customdata[1]} incidentes · %{y:.1f} %<extra></extra>',
    )
    figura.update_xaxes(
        title_text='Primera llegada (min)', type='category', autotickangles=[0, 30],
        fixedrange=True, automargin=True, tickfont=dict(size=11),
    )
    figura.update_yaxes(
        title_text='Incidentes con tiempo válido', ticksuffix=' %', rangemode='tozero',
        gridcolor='#e8e5db', zeroline=False, fixedrange=True, automargin=True,
    )

    validos_texto = f'{validos:,}'.replace(',', '\u202f')
    total_texto = f'{total:,}'.replace(',', '\u202f')
    cola_texto = f'{frecuencias[-1]:,}'.replace(',', '\u202f')
    cola_pct = f'{porcentajes[-1]:.1f}'.replace('.', ',')
    nota = (
        f'{validos_texto} de {total_texto} incidentes con tiempo válido. '
        f'{cola_texto} ({cola_pct} %) en 15 min o más.'
    )
    return figura, nota
