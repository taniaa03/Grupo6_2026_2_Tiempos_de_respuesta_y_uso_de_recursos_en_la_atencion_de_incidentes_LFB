# Código del proyecto: ETL y carga del modelo

Construye el datamart del proyecto en SQL Server a partir de los registros oficiales de London Fire Brigade (CalYear=2025). La base se aloja en **MonsterASP** (SQL Server remoto); también puede cargarse en un SQL Server local.

| Archivo | Qué hace |
|---|---|
| [`etl/cargar_sql.py`](etl/cargar_sql.py) | Se conecta al SQL Server (MonsterASP o local), crea las tablas, sube el staging, puebla el modelo, muestra las validaciones y vacía el staging. |
| [`etl/etl_lfb.py`](etl/etl_lfb.py) | Lee los originales, filtra 2025, limpia, deduplica movilizaciones, separa IDs contradictorios y calcula los controles de enlace. Escribe el staging en `data/processed/` y el resumen en [`data/resumen_calidad_etl.json`](../data/resumen_calidad_etl.json). |
| [`sql/01_crear_modelo.sql`](sql/01_crear_modelo.sql) | Crea el esquema `stg`, las 8 dimensiones y los 2 hechos con PK y FK en la base activa. |
| [`sql/02_cargar_staging_csv.sql`](sql/02_cargar_staging_csv.sql) | Solo SQL Server local: carga los CSV con BULK INSERT (alternativa a `cargar_sql.py`). |
| [`sql/03_poblar_modelo.sql`](sql/03_poblar_modelo.sql) | Puebla dimensiones (miembro 0, IDENTITY, catálogos) y hechos mediante lookups. |
| [`sql/04_validaciones.sql`](sql/04_validaciones.sql) | Controles de calidad: conteos, filas perdidas, uso de la clave 0, enlace entre hechos y coherencia de tiempos. |

## Pasos

1. Descargar los dos archivos fuente en `data/raw/recientes/` según [data/README.md](../data/README.md).
2. Instalar dependencias y ejecutar el ETL (≈1–2 min):

   ```bash
   pip install -r requirements.txt
   python src/etl/etl_lfb.py
   ```

3. Instalar el [ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server) si no está instalado.
4. Cargar en MonsterASP. Los datos de conexión (servidor, base, usuario y contraseña) están en el panel de MonsterASP, sección *Databases*:

   ```bash
   python src/etl/cargar_sql.py --servidor <servidor> --base <base> --usuario <usuario>
   ```

   El script pide la contraseña por teclado; **no escribirla en archivos del repositorio**. Tarda varios minutos según la conexión (≈3 min en red local). Al final muestra las validaciones y vacía el staging: el modelo final ocupa ≈33 MB.

Para recargar, basta volver a ejecutar `cargar_sql.py`: recrea dimensiones y hechos.

### Alternativa: SQL Server local desde SSMS

Crear la base (`CREATE DATABASE LFB_DW;`), seleccionarla y ejecutar en orden `01`, `02` (cambiando `@ruta` por la carpeta `data\processed\`), `03` y `04`. También se puede usar `cargar_sql.py --servidor localhost --base LFB_DW --usuario <usuario>`.

## Resultado de referencia

Ejecución con la descarga del 14/11/2026 (SQL Server 2022, con `cargar_sql.py` y con los scripts en SSMS):

| Tabla | Filas |
|---|---|
| DimFecha | 366 (365 días + desconocido) |
| DimHora | 25 |
| DimTipoIncidente | 42 |
| DimTipoPropiedad | 273 |
| DimGeografia | 1 772 |
| DimEstacion | 112 |
| DimOrigenDespliegue | 3 |
| DimMotivoDemora | 11 |
| FactIncidente | 137 981 |
| FactMovilizacion | 206 682 |

Calidad de datos de movilizaciones 2025: 207 982 leídas, 1 270 copias idénticas eliminadas y 15 IDs con versiones contradictorias (30 filas) separados en `data/processed/movilizaciones_con_conflicto.csv`. Hay 7 384 incidentes sin movilización enlazada y 799 movilizaciones sin incidente (claves compartidas = 0, `TieneIncidente=0`).

Validaciones: 0 filas perdidas entre staging y hechos; en las 205 728 movilizaciones con los tres tiempos, `LlegadaSeg = SalidaSeg + ViajeSeg` sin excepciones. 38 wards aparecen con dos boroughs: son incidentes aislados de frontera (p. ej. 354 en Tower Hamlets y 1 en City of London para el mismo ward); la dimensión conserva la combinación publicada.

El proveedor actualiza los archivos en los mismos enlaces, por lo que una descarga posterior puede variar ligeramente.
