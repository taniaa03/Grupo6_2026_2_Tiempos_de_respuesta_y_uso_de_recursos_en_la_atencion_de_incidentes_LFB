"""ETL de London Fire Brigade (CalYear=2025) para el modelo multidimensional.

Pasos:
  1. Extrae los archivos originales de data/raw/recientes/ (no se modifican).
  2. Filtra CalYear=2025, limpia tipos y textos, aplica las reglas del modelo:
     - Movilizaciones: elimina copias idénticas y separa los IDs con versiones
       contradictorias (se guardan aparte para revisión, no se cargan).
     - Calcula TieneMovilizacion / TieneIncidente.
     - Valores ausentes de atributos -> 'Desconocido' (clave 0 en SQL).
  3. Escribe los datos de staging en data/processed/ (CSV UTF-8) y el resumen
     de calidad en data/resumen_calidad_etl.json.
Luego se cargan en SQL Server con src/sql/ (ver src/README.md).

Uso:
  python src/etl/etl_lfb.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
RAW = RAIZ / "data" / "raw" / "recientes"
SALIDA = RAIZ / "data" / "processed"
ARCHIVO_INC = RAW / "incidentes_2024_hasta_julio_2026.xlsx"
ARCHIVO_MOB = RAW / "movilizaciones_2025_hasta_julio_2026.csv"
ANIO = "2025"
DESCONOCIDO = "Desconocido"


def texto(serie: pd.Series) -> pd.Series:
    """Quita espacios; vacíos -> NA."""
    s = serie.astype("string").str.strip()
    return s.mask(s == "", pd.NA)


def entero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce").round().astype("Int64")


def extraer() -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"Leyendo {ARCHIVO_INC.name} (puede tardar ~1 min)...")
    inc = pd.read_excel(ARCHIVO_INC, dtype=str)
    print(f"Leyendo {ARCHIVO_MOB.name}...")
    mob = pd.read_csv(ARCHIVO_MOB, dtype=str, encoding="utf-8-sig")
    return inc, mob


def transformar_incidentes(inc: pd.DataFrame) -> pd.DataFrame:
    inc = inc[texto(inc["CalYear"]) == ANIO].copy()
    df = pd.DataFrame()
    df["IncidentNumber"] = texto(inc["IncidentNumber"])
    fecha = pd.to_datetime(inc["DateOfCall"], errors="coerce")
    df["Fecha"] = fecha.dt.date
    df["Hora"] = entero(inc["HourOfCall"])

    grupo = texto(inc["IncidentGroup"])
    df["Grupo"] = grupo.fillna(DESCONOCIDO)
    df["Clasificacion"] = texto(inc["StopCodeDescription"]).fillna(DESCONOCIDO)
    # No aplica fuera de Special Service; Desconocido si falta dentro de ese grupo
    # o si el grupo mismo es desconocido.
    es_servicio = grupo.eq("Special Service").fillna(False).astype(bool)
    servicio = texto(inc["SpecialServiceType"]).fillna(DESCONOCIDO)
    df["ServicioEspecial"] = servicio.where(es_servicio | grupo.isna(), "No aplica")
    df.loc[grupo.isna().to_numpy(), "ServicioEspecial"] = DESCONOCIDO

    df["Categoria"] = texto(inc["PropertyCategory"]).fillna(DESCONOCIDO)
    df["TipoPropiedad"] = texto(inc["PropertyType"]).fillna(DESCONOCIDO)

    df["BoroughCodigo"] = texto(inc["IncGeo_BoroughCode"]).fillna(DESCONOCIDO)
    df["BoroughNombre"] = texto(inc["IncGeo_BoroughName"]).fillna(DESCONOCIDO)
    df["WardCodigo"] = texto(inc["IncGeo_WardCode"]).fillna(DESCONOCIDO)
    df["WardNombre"] = texto(inc["IncGeo_WardName"]).fillna(DESCONOCIDO)
    df["DistritoPostal"] = texto(inc["Postcode_district"]).fillna(DESCONOCIDO)

    df["PrimerArriboSeg"] = entero(inc["FirstPumpArriving_AttendanceTime"])
    df["SegundoArriboSeg"] = entero(inc["SecondPumpArriving_AttendanceTime"])
    df["NumEstaciones"] = entero(inc["NumStationsWithPumpsAttending"])
    df["NumBombas"] = entero(inc["NumPumpsAttending"])
    df["MinutosBombaRedondeados"] = entero(inc["PumpMinutesRounded"])
    df["CostoNocionalGBP"] = pd.to_numeric(inc["Notional Cost (£)"], errors="coerce").round(2)
    df["NumLlamadas"] = entero(inc["NumCalls"])

    if df["IncidentNumber"].duplicated().any():
        raise ValueError("IncidentNumber repetido en incidentes 2025: revisar la fuente.")
    return df.reset_index(drop=True)


def transformar_movilizaciones(mob: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    mob = mob[texto(mob["CalYear"]) == ANIO].copy()
    calidad = {"movilizaciones_2025_leidas": len(mob)}

    sin_copias = mob.drop_duplicates()
    calidad["copias_identicas_eliminadas"] = len(mob) - len(sin_copias)

    repetido = sin_copias["ResourceMobilisationId"].duplicated(keep=False)
    conflictos = sin_copias[repetido].sort_values("ResourceMobilisationId")
    validas = sin_copias[~repetido]
    calidad["filas_con_versiones_contradictorias"] = int(repetido.sum())
    calidad["ids_con_versiones_contradictorias"] = int(conflictos["ResourceMobilisationId"].nunique())

    df = pd.DataFrame()
    df["ResourceMobilisationId"] = entero(validas["ResourceMobilisationId"])
    df["IncidentNumber"] = texto(validas["IncidentNumber"])
    df["EstacionCodigo"] = texto(validas["DeployedFromStation_Code"])
    df["EstacionNombre"] = texto(validas["DeployedFromStation_Name"])
    origen = texto(validas["DeployedFromLocation"])
    df["OrigenDespliegueKey"] = origen.map({"Home Station": 1, "Other Station": 2}).fillna(0).astype(int)
    codigo = texto(validas["DelayCodeId"])
    df["DemoraCodigo"] = codigo
    df["MotivoDemoraKey"] = entero(codigo).fillna(0)
    df["DemoraDescripcion"] = texto(validas["DelayCode_Description"])
    df["ResourceCodigo"] = texto(validas["Resource_Code"])
    df["PerformanceReporting"] = texto(validas["PerformanceReporting"])
    df["FechaHoraMovilizada"] = pd.to_datetime(
        validas["DateAndTimeMobilised"], format="%d/%m/%Y %H:%M", errors="coerce"
    )
    df["SalidaSeg"] = entero(validas["TurnoutTimeSeconds"])
    df["ViajeSeg"] = entero(validas["TravelTimeSeconds"])
    df["LlegadaSeg"] = entero(validas["AttendanceTimeSeconds"])

    if (df["MotivoDemoraKey"] < 0).any():
        raise ValueError("DelayCodeId negativo: revisar la regla de DimMotivoDemora.")
    calidad["movilizaciones_validas"] = len(df)
    return df.reset_index(drop=True), conflictos, calidad


def enlazar(inc: pd.DataFrame, mob: pd.DataFrame, calidad: dict) -> None:
    inc["TieneMovilizacion"] = inc["IncidentNumber"].isin(mob["IncidentNumber"]).astype(int)
    mob["TieneIncidente"] = mob["IncidentNumber"].isin(inc["IncidentNumber"]).astype(int)
    calidad["incidentes_2025"] = len(inc)
    calidad["incidentes_sin_movilizacion_enlazada"] = int((inc["TieneMovilizacion"] == 0).sum())
    calidad["movilizaciones_sin_incidente_enlazado"] = int((mob["TieneIncidente"] == 0).sum())
    calidad["incidentes_por_grupo"] = inc["Grupo"].value_counts().to_dict()


def guardar(inc, mob, conflictos, calidad) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    inc.to_csv(SALIDA / "stg_incidente.csv", index=False, encoding="utf-8")
    mob.to_csv(SALIDA / "stg_movilizacion.csv", index=False, encoding="utf-8",
               date_format="%Y-%m-%d %H:%M:%S")
    conflictos.to_csv(SALIDA / "movilizaciones_con_conflicto.csv", index=False, encoding="utf-8")
    with open(RAIZ / "data" / "resumen_calidad_etl.json", "w", encoding="utf-8") as f:
        json.dump(calidad, f, ensure_ascii=False, indent=2)
    print(json.dumps(calidad, ensure_ascii=False, indent=2))
    print(f"Archivos de staging escritos en {SALIDA}")


def main() -> None:
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    inc_raw, mob_raw = extraer()
    inc = transformar_incidentes(inc_raw)
    mob, conflictos, calidad = transformar_movilizaciones(mob_raw)
    enlazar(inc, mob, calidad)
    guardar(inc, mob, conflictos, calidad)


if __name__ == "__main__":
    main()
