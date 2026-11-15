-- Ejecutar en el datamart con una cuenta que pueda crear usuarios y dar permisos.
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF DATABASE_PRINCIPAL_ID(N'lfb_lector_consultas') IS NULL
        CREATE USER lfb_lector_consultas WITHOUT LOGIN WITH DEFAULT_SCHEMA = dbo;

    DECLARE @lector int = DATABASE_PRINCIPAL_ID(N'lfb_lector_consultas');
    IF NOT EXISTS (
        SELECT 1 FROM sys.database_principals
        WHERE principal_id = @lector AND type = 'S' AND authentication_type = 0
    ) OR EXISTS (
        SELECT 1 FROM sys.database_role_members WHERE member_principal_id = @lector
    ) OR EXISTS (
        SELECT 1 FROM sys.schemas WHERE principal_id = @lector
        UNION ALL
        SELECT 1 FROM sys.objects WHERE principal_id = @lector
    )
        THROW 50001, 'El lector de la consola debe ser un usuario sin login, roles ni objetos propios.', 1;

    DECLARE @tablas TABLE (ObjetoId int NULL);
    INSERT INTO @tablas (ObjetoId) VALUES
        (OBJECT_ID(N'dbo.DimFecha', 'U')), (OBJECT_ID(N'dbo.DimHora', 'U')),
        (OBJECT_ID(N'dbo.DimTipoIncidente', 'U')), (OBJECT_ID(N'dbo.DimTipoPropiedad', 'U')),
        (OBJECT_ID(N'dbo.DimGeografia', 'U')), (OBJECT_ID(N'dbo.DimEstacion', 'U')),
        (OBJECT_ID(N'dbo.DimOrigenDespliegue', 'U')), (OBJECT_ID(N'dbo.DimMotivoDemora', 'U')),
        (OBJECT_ID(N'dbo.FactIncidente', 'U')), (OBJECT_ID(N'dbo.FactMovilizacion', 'U')),
        (OBJECT_ID(N'dbo.CuboIncidentes', 'V')), (OBJECT_ID(N'dbo.CuboMovilizaciones', 'V'));

    IF EXISTS (SELECT 1 FROM @tablas WHERE ObjetoId IS NULL)
        THROW 50003, N'Primero crea las tablas y los dos cubos del datamart.', 1;

    IF EXISTS (
        SELECT 1 FROM sys.database_permissions AS p
        WHERE p.grantee_principal_id = @lector AND p.state IN ('G', 'W')
          AND NOT (p.state = 'G' AND (
                       (p.class = 0 AND p.permission_name = 'CONNECT')
                    OR (p.class = 1 AND p.minor_id = 0 AND p.permission_name = 'SELECT'
                        AND EXISTS (SELECT 1 FROM @tablas AS t WHERE t.ObjetoId = p.major_id))
          ))
    )
        THROW 50002, 'El lector de la consola tiene permisos adicionales. Revísalos antes de continuar.', 1;

    GRANT SELECT ON OBJECT::dbo.DimFecha TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimHora TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimTipoIncidente TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimTipoPropiedad TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimGeografia TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimEstacion TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimOrigenDespliegue TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.DimMotivoDemora TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.FactIncidente TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.FactMovilizacion TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.CuboIncidentes TO lfb_lector_consultas;
    GRANT SELECT ON OBJECT::dbo.CuboMovilizaciones TO lfb_lector_consultas;
    DENY INSERT, UPDATE, DELETE, EXECUTE, ALTER, TAKE OWNERSHIP TO lfb_lector_consultas;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

-- Si la cuenta del tablero tiene permisos limitados, dar solo esta suplantación:
-- GRANT IMPERSONATE ON USER::lfb_lector_consultas TO [usuario_del_tablero];
