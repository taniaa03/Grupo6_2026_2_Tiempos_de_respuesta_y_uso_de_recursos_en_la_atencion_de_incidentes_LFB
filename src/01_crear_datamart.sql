IF OBJECT_ID('dbo.DimFecha', 'U') IS NULL
    CREATE TABLE dbo.DimFecha (
        FechaKey int PRIMARY KEY,
        Fecha date,
        Anio smallint,
        Trimestre tinyint,
        Mes tinyint,
        Dia tinyint,
        DiaSemana tinyint
    );

IF OBJECT_ID('dbo.DimHora', 'U') IS NULL
    CREATE TABLE dbo.DimHora (
        HoraKey int PRIMARY KEY,
        Hora tinyint,
        Franja nvarchar(30) NOT NULL
    );

IF OBJECT_ID('dbo.DimTipoIncidente', 'U') IS NULL
    CREATE TABLE dbo.DimTipoIncidente (
        TipoIncidenteKey int IDENTITY(1,1) PRIMARY KEY,
        Grupo nvarchar(100) NOT NULL,
        Clasificacion nvarchar(200) NOT NULL,
        ServicioEspecial nvarchar(200) NOT NULL,
        UNIQUE (Grupo, Clasificacion, ServicioEspecial)
    );

IF OBJECT_ID('dbo.DimTipoPropiedad', 'U') IS NULL
    CREATE TABLE dbo.DimTipoPropiedad (
        TipoPropiedadKey int IDENTITY(1,1) PRIMARY KEY,
        Categoria nvarchar(100) NOT NULL,
        Tipo nvarchar(200) NOT NULL,
        UNIQUE (Categoria, Tipo)
    );

IF OBJECT_ID('dbo.DimGeografia', 'U') IS NULL
    CREATE TABLE dbo.DimGeografia (
        GeografiaKey int IDENTITY(1,1) PRIMARY KEY,
        BoroughCodigo nvarchar(30) NOT NULL,
        BoroughNombre nvarchar(120) NOT NULL,
        WardCodigo nvarchar(30) NOT NULL,
        WardNombre nvarchar(150) NOT NULL,
        DistritoPostal nvarchar(30) NOT NULL,
        UNIQUE (BoroughCodigo, BoroughNombre, WardCodigo, WardNombre, DistritoPostal)
    );

IF OBJECT_ID('dbo.DimEstacion', 'U') IS NULL
    CREATE TABLE dbo.DimEstacion (
        EstacionKey int IDENTITY(1,1) PRIMARY KEY,
        Codigo nvarchar(30) NOT NULL UNIQUE,
        Nombre nvarchar(150) NOT NULL
    );

IF OBJECT_ID('dbo.DimOrigenDespliegue', 'U') IS NULL
    CREATE TABLE dbo.DimOrigenDespliegue (
        OrigenDespliegueKey int PRIMARY KEY,
        Origen nvarchar(50) NOT NULL UNIQUE
    );

IF OBJECT_ID('dbo.DimMotivoDemora', 'U') IS NULL
    CREATE TABLE dbo.DimMotivoDemora (
        MotivoDemoraKey int PRIMARY KEY,
        Codigo nvarchar(30) NOT NULL UNIQUE,
        Descripcion nvarchar(200) NOT NULL
    );

IF OBJECT_ID('dbo.FactIncidente', 'U') IS NULL
    CREATE TABLE dbo.FactIncidente (
        IncidentNumber varchar(30) PRIMARY KEY,
        AnioFuente smallint NOT NULL CHECK (AnioFuente BETWEEN 2021 AND 2025),
        FechaKey int NOT NULL REFERENCES dbo.DimFecha(FechaKey),
        HoraKey int NOT NULL REFERENCES dbo.DimHora(HoraKey),
        TipoIncidenteKey int NOT NULL REFERENCES dbo.DimTipoIncidente(TipoIncidenteKey),
        TipoPropiedadKey int NOT NULL REFERENCES dbo.DimTipoPropiedad(TipoPropiedadKey),
        GeografiaKey int NOT NULL REFERENCES dbo.DimGeografia(GeografiaKey),
        PrimerArriboSeg int,
        SegundoArriboSeg int,
        NumEstaciones int,
        NumBombas int,
        MinutosBombaRedondeados int,
        CostoNocionalGBP decimal(18,2),
        NumLlamadas int,
        TieneMovilizacion bit NOT NULL
    );

IF OBJECT_ID('dbo.FactMovilizacion', 'U') IS NULL
    CREATE TABLE dbo.FactMovilizacion (
        ResourceMobilisationId bigint PRIMARY KEY,
        AnioFuente smallint NOT NULL CHECK (AnioFuente BETWEEN 2021 AND 2025),
        IncidentNumber varchar(30),
        FechaKey int NOT NULL REFERENCES dbo.DimFecha(FechaKey),
        HoraKey int NOT NULL REFERENCES dbo.DimHora(HoraKey),
        TipoIncidenteKey int NOT NULL REFERENCES dbo.DimTipoIncidente(TipoIncidenteKey),
        TipoPropiedadKey int NOT NULL REFERENCES dbo.DimTipoPropiedad(TipoPropiedadKey),
        GeografiaKey int NOT NULL REFERENCES dbo.DimGeografia(GeografiaKey),
        EstacionKey int NOT NULL REFERENCES dbo.DimEstacion(EstacionKey),
        OrigenDespliegueKey int NOT NULL REFERENCES dbo.DimOrigenDespliegue(OrigenDespliegueKey),
        MotivoDemoraKey int NOT NULL REFERENCES dbo.DimMotivoDemora(MotivoDemoraKey),
        ResourceCodigo nvarchar(30),
        PerformanceReporting nvarchar(30),
        FechaHoraMovilizada datetime2(0),
        SalidaSeg int,
        ViajeSeg int,
        LlegadaSeg int,
        TieneIncidente bit NOT NULL
    );
