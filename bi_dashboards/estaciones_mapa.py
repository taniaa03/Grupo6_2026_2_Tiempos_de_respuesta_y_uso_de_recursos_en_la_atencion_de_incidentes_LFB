from filtro_subgrupo import columna_subgrupo


def estaciones_por_municipio(conectar, anio, grupo, subgrupo='todos'):
    condiciones = ['m.EstacionKey > 0', 'm.GeografiaKey > 0', 'm.TieneIncidente = 1']
    valores = []
    uniones = []
    for campo, valor, union in (
        ('m.AnioFuente', anio, ''),
        ('t.Grupo', grupo, 'INNER JOIN dbo.DimTipoIncidente AS t ON t.TipoIncidenteKey = m.TipoIncidenteKey'),
        (columna_subgrupo(grupo), subgrupo, ''),
    ):
        if valor != 'todos':
            condiciones.append(f'{campo} = ?')
            valores.append(valor)
            uniones.append(union)

    sql = f'''
        WITH movimientos AS (
            SELECT m.GeografiaKey, m.EstacionKey, COUNT_BIG(*) AS Movilizaciones
            FROM dbo.FactMovilizacion AS m
            {' '.join(uniones)}
            WHERE {' AND '.join(condiciones)}
            GROUP BY m.GeografiaKey, m.EstacionKey
        )
        SELECT g.BoroughNombre, e.Codigo, e.Nombre, SUM(m.Movilizaciones) AS Movilizaciones
        FROM movimientos AS m
        INNER JOIN dbo.DimGeografia AS g ON g.GeografiaKey = m.GeografiaKey
        INNER JOIN dbo.DimEstacion AS e ON e.EstacionKey = m.EstacionKey
        WHERE LTRIM(RTRIM(g.BoroughNombre)) NOT IN (N'', N'Desconocido')
        GROUP BY g.BoroughNombre, e.Codigo, e.Nombre
        ORDER BY g.BoroughNombre, Movilizaciones DESC, e.Codigo;
    '''
    conn = conectar()
    try:
        filas = conn.cursor().execute(sql, *valores).fetchall()
    finally:
        conn.close()

    estaciones = {}
    for municipio, codigo, nombre, movilizaciones in filas:
        estaciones.setdefault(municipio, []).append({
            'codigo': codigo,
            'nombre': nombre,
            'movilizaciones': movilizaciones,
        })
    return estaciones
