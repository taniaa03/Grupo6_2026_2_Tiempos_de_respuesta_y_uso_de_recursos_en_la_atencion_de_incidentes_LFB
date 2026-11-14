/* =====================================================================
   01_crear_modelo.sql
   Crea el esquema de staging y el modelo multidimensional (8 dimensiones,
   2 tablas de hechos) descrito en el README §6, en la base de datos activa.
   - Local: crear antes la base (CREATE DATABASE LFB_DW;) y seleccionarla.
   - MonsterASP u otro hosting: la base ya existe; conectarse a ella.
   Lo ejecuta src/etl/cargar_sql.py, o manualmente desde SSMS.
   Es re-ejecutable: elimina y vuelve a crear dimensiones y hechos.
   Las tablas de staging solo se crean si no existen, para no perder la carga.
   ===================================================================== */

IF SCHEMA_ID(N'stg') IS NULL EXEC (N'CREATE SCHEMA stg');
GO

/* ---------- Limpieza (orden inverso a las FK) ---------- */
DROP TABLE IF EXISTS dbo.FactMovilizacion;
DROP TABLE IF EXISTS dbo.FactIncidente;
DROP TABLE IF EXISTS dbo.DimFecha;
DROP TABLE IF EXISTS dbo.DimHora;
DROP TABLE IF EXISTS dbo.DimTipoIncidente;
DROP TABLE IF EXISTS dbo.DimTipoPropiedad;
DROP TABLE IF EXISTS dbo.DimGeografia;
DROP TABLE IF EXISTS dbo.DimEstacion;
DROP TABLE IF EXISTS dbo.DimOrigenDespliegue;
DROP TABLE IF EXISTS dbo.DimMotivoDemora;
GO

/* ---------- Staging: salida de src/etl/etl_lfb.py ---------- */
IF OBJECT_ID(N'stg.Incidente') IS NULL
CREATE TABLE stg.Incidente (
    IncidentNumber          varchar(30)    NOT NULL,
    Fecha                   date           NULL,
    Hora                    tinyint        NULL,
    Grupo                   nvarchar(100)  NOT NULL,
    Clasificacion           nvarchar(200)  NOT NULL,
    ServicioEspecial        nvarchar(200)  NOT NULL,
    Categoria               nvarchar(100)  NOT NULL,
    TipoPropiedad           nvarchar(200)  NOT NULL,
    BoroughCodigo           nvarchar(30)   NOT NULL,
    BoroughNombre           nvarchar(120)  NOT NULL,
    WardCodigo              nvarchar(30)   NOT NULL,
    WardNombre              nvarchar(150)  NOT NULL,
    DistritoPostal          nvarchar(30)   NOT NULL,
    PrimerArriboSeg         int            NULL,
    SegundoArriboSeg        int            NULL,
    NumEstaciones           int            NULL,
    NumBombas               int            NULL,
    MinutosBombaRedondeados int            NULL,
    CostoNocionalGBP        decimal(18,2)  NULL,
    NumLlamadas             int            NULL,
    TieneMovilizacion       bit            NOT NULL
);

IF OBJECT_ID(N'stg.Movilizacion') IS NULL
CREATE TABLE stg.Movilizacion (
    ResourceMobilisationId  bigint         NOT NULL,
    IncidentNumber          varchar(30)    NULL,
    EstacionCodigo          nvarchar(30)   NULL,
    EstacionNombre          nvarchar(150)  NULL,
    OrigenDespliegueKey     int            NOT NULL,
    DemoraCodigo            nvarchar(30)   NULL,
    MotivoDemoraKey         int            NOT NULL,
    DemoraDescripcion       nvarchar(200)  NULL,
    ResourceCodigo          nvarchar(30)   NULL,
    PerformanceReporting    nvarchar(30)   NULL,
    FechaHoraMovilizada     datetime2(0)   NULL,
    SalidaSeg               int            NULL,
    ViajeSeg                int            NULL,
    LlegadaSeg              int            NULL,
    TieneIncidente          bit            NOT NULL
);
GO

/* ---------- Dimensiones ---------- */
CREATE TABLE dbo.DimFecha (
    FechaKey   int      NOT NULL CONSTRAINT PK_DimFecha PRIMARY KEY,
    Fecha      date     NULL,
    Anio       smallint NULL,
    Trimestre  tinyint  NULL,
    Mes        tinyint  NULL,
    Dia        tinyint  NULL,
    DiaSemana  tinyint  NULL
);

CREATE TABLE dbo.DimHora (
    HoraKey  int          NOT NULL CONSTRAINT PK_DimHora PRIMARY KEY,
    Hora     tinyint      NULL,
    Franja   nvarchar(30) NOT NULL
);

CREATE TABLE dbo.DimTipoIncidente (
    TipoIncidenteKey int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimTipoIncidente PRIMARY KEY,
    Grupo            nvarchar(100) NOT NULL,
    Clasificacion    nvarchar(200) NOT NULL,
    ServicioEspecial nvarchar(200) NOT NULL,
    CONSTRAINT UQ_DimTipoIncidente UNIQUE (Grupo, Clasificacion, ServicioEspecial)
);

CREATE TABLE dbo.DimTipoPropiedad (
    TipoPropiedadKey int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimTipoPropiedad PRIMARY KEY,
    Categoria        nvarchar(100) NOT NULL,
    Tipo             nvarchar(200) NOT NULL,
    CONSTRAINT UQ_DimTipoPropiedad UNIQUE (Categoria, Tipo)
);

CREATE TABLE dbo.DimGeografia (
    GeografiaKey   int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimGeografia PRIMARY KEY,
    BoroughCodigo  nvarchar(30)  NOT NULL,
    BoroughNombre  nvarchar(120) NOT NULL,
    WardCodigo     nvarchar(30)  NOT NULL,
    WardNombre     nvarchar(150) NOT NULL,
    DistritoPostal nvarchar(30)  NOT NULL,
    CONSTRAINT UQ_DimGeografia UNIQUE (BoroughCodigo, BoroughNombre, WardCodigo, WardNombre, DistritoPostal)
);

CREATE TABLE dbo.DimEstacion (
    EstacionKey int IDENTITY(1,1) NOT NULL CONSTRAINT PK_DimEstacion PRIMARY KEY,
    Codigo      nvarchar(30)  NOT NULL CONSTRAINT UQ_DimEstacion UNIQUE,
    Nombre      nvarchar(150) NOT NULL
);

CREATE TABLE dbo.DimOrigenDespliegue (
    OrigenDespliegueKey int          NOT NULL CONSTRAINT PK_DimOrigenDespliegue PRIMARY KEY,
    Origen              nvarchar(50) NOT NULL
);

CREATE TABLE dbo.DimMotivoDemora (
    MotivoDemoraKey int           NOT NULL CONSTRAINT PK_DimMotivoDemora PRIMARY KEY,
    Codigo          nvarchar(30)  NOT NULL,
    Descripcion     nvarchar(200) NOT NULL
);
GO

/* ---------- Hechos ---------- */
CREATE TABLE dbo.FactIncidente (
    IncidentNumber          varchar(30)   NOT NULL CONSTRAINT PK_FactIncidente PRIMARY KEY,
    FechaKey                int           NOT NULL CONSTRAINT FK_FI_Fecha         REFERENCES dbo.DimFecha(FechaKey),
    HoraKey                 int           NOT NULL CONSTRAINT FK_FI_Hora          REFERENCES dbo.DimHora(HoraKey),
    TipoIncidenteKey        int           NOT NULL CONSTRAINT FK_FI_TipoIncidente REFERENCES dbo.DimTipoIncidente(TipoIncidenteKey),
    TipoPropiedadKey        int           NOT NULL CONSTRAINT FK_FI_TipoPropiedad REFERENCES dbo.DimTipoPropiedad(TipoPropiedadKey),
    GeografiaKey            int           NOT NULL CONSTRAINT FK_FI_Geografia     REFERENCES dbo.DimGeografia(GeografiaKey),
    PrimerArriboSeg         int           NULL,
    SegundoArriboSeg        int           NULL,
    NumEstaciones           int           NULL,
    NumBombas               int           NULL,
    MinutosBombaRedondeados int           NULL,
    CostoNocionalGBP        decimal(18,2) NULL,
    NumLlamadas             int           NULL,
    TieneMovilizacion       bit           NOT NULL
);

CREATE TABLE dbo.FactMovilizacion (
    ResourceMobilisationId bigint       NOT NULL CONSTRAINT PK_FactMovilizacion PRIMARY KEY,
    IncidentNumber         varchar(30)  NULL,
    FechaKey               int          NOT NULL CONSTRAINT FK_FM_Fecha            REFERENCES dbo.DimFecha(FechaKey),
    HoraKey                int          NOT NULL CONSTRAINT FK_FM_Hora             REFERENCES dbo.DimHora(HoraKey),
    TipoIncidenteKey       int          NOT NULL CONSTRAINT FK_FM_TipoIncidente    REFERENCES dbo.DimTipoIncidente(TipoIncidenteKey),
    TipoPropiedadKey       int          NOT NULL CONSTRAINT FK_FM_TipoPropiedad    REFERENCES dbo.DimTipoPropiedad(TipoPropiedadKey),
    GeografiaKey           int          NOT NULL CONSTRAINT FK_FM_Geografia        REFERENCES dbo.DimGeografia(GeografiaKey),
    EstacionKey            int          NOT NULL CONSTRAINT FK_FM_Estacion         REFERENCES dbo.DimEstacion(EstacionKey),
    OrigenDespliegueKey    int          NOT NULL CONSTRAINT FK_FM_OrigenDespliegue REFERENCES dbo.DimOrigenDespliegue(OrigenDespliegueKey),
    MotivoDemoraKey        int          NOT NULL CONSTRAINT FK_FM_MotivoDemora     REFERENCES dbo.DimMotivoDemora(MotivoDemoraKey),
    ResourceCodigo         nvarchar(30) NULL,
    PerformanceReporting   nvarchar(30) NULL,
    FechaHoraMovilizada    datetime2(0) NULL,
    SalidaSeg              int          NULL,
    ViajeSeg               int          NULL,
    LlegadaSeg             int          NULL,
    TieneIncidente         bit          NOT NULL
);
GO

PRINT 'Tablas del modelo creadas.';
