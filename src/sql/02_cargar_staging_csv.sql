/* =====================================================================
   02_cargar_staging_csv.sql  (solo SQL Server local)
   En un hosting como MonsterASP usar src/etl/cargar_sql.py: BULK INSERT
   necesita que los CSV estén en el disco del propio servidor.
   Carga los CSV generados por src/etl/etl_lfb.py en el esquema stg.
   1. Reemplazar @ruta por la carpeta data\processed de su copia del repo
      (debe ser accesible por el servicio de SQL Server).
   2. Ejecutar. Requiere SQL Server 2017+ (BULK INSERT con FORMAT='CSV').
   ===================================================================== */

DECLARE @ruta nvarchar(400) = N'C:\ruta\al\repo\London\data\processed\';
DECLARE @sql  nvarchar(max);

TRUNCATE TABLE stg.Incidente;
TRUNCATE TABLE stg.Movilizacion;

SET @sql = N'BULK INSERT stg.Incidente FROM ''' + @ruta + N'stg_incidente.csv''
WITH (FORMAT = ''CSV'', FIRSTROW = 2, CODEPAGE = ''65001'', FIELDQUOTE = ''"'', KEEPNULLS, TABLOCK);';
EXEC (@sql);

SET @sql = N'BULK INSERT stg.Movilizacion FROM ''' + @ruta + N'stg_movilizacion.csv''
WITH (FORMAT = ''CSV'', FIRSTROW = 2, CODEPAGE = ''65001'', FIELDQUOTE = ''"'', KEEPNULLS, TABLOCK);';
EXEC (@sql);

SELECT 'stg.Incidente' AS tabla, COUNT(*) AS filas FROM stg.Incidente
UNION ALL
SELECT 'stg.Movilizacion', COUNT(*) FROM stg.Movilizacion;
-- Esperado (descarga del 14/11/2026): 137 981 y 206 682. Comparar con data/resumen_calidad_etl.json.
