"""Carga el modelo LFB en un SQL Server remoto (MonsterASP) o local.

Requiere haber ejecutado antes  python src/etl/etl_lfb.py  (genera data/processed/).

Pasos que realiza, en la base indicada:
  1. src/sql/01_crear_modelo.sql   -> crea staging, dimensiones y hechos.
  2. Inserta data/processed/stg_*.csv en stg.Incidente y stg.Movilizacion.
  3. src/sql/03_poblar_modelo.sql  -> puebla dimensiones y hechos.
  4. src/sql/04_validaciones.sql   -> muestra los controles de calidad.
  5. Vacía el staging para ahorrar espacio (el modelo final ocupa ~33 MB).

Uso (los datos de conexión están en el panel de MonsterASP, sección Databases):
  python src/etl/cargar_sql.py --servidor db12345.public.databaseasp.net --base db12345 --usuario db12345

La contraseña se pide por teclado, o se toma de la variable de entorno LFB_SQL_PASSWORD.
Nunca escribirla en el código ni subirla a GitHub.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyodbc

RAIZ = Path(__file__).resolve().parents[2]
SQL = RAIZ / "src" / "sql"
PROCESADOS = RAIZ / "data" / "processed"
LOTE = 10000



def conectar(a: argparse.Namespace) -> pyodbc.Connection:
    clave = os.environ.get("LFB_SQL_PASSWORD") or getpass.getpass(f"Contraseña de {a.usuario}: ")
    cadena = (
        f"DRIVER={{{a.driver}}};SERVER={a.servidor};DATABASE={a.base};"
        f"UID={a.usuario};PWD={clave};Encrypt=yes;TrustServerCertificate=yes;"
        "Connection Timeout=30"
    )
    cx = pyodbc.connect(cadena, autocommit=True)
    print(f"Conectado a {a.servidor} / {a.base}")
    return cx


def ejecutar_script(cx: pyodbc.Connection, archivo: Path, mostrar: bool = False) -> None:
    """Ejecuta un .sql dividiéndolo en lotes por las líneas GO."""
    print(f"\n== {archivo.name}")
    texto = archivo.read_text(encoding="utf-8")
    cur = cx.cursor()
    for lote in re.split(r"^\s*GO\s*$", texto, flags=re.M | re.I):
        if not lote.strip():
            continue
        cur.execute(lote)
        while True:
            for _, msg in cur.messages:
                print("  ", re.sub(r"^(\[[^\]]*\])+", "", msg))
            if mostrar and cur.description:
                cols = [c[0] for c in cur.description]
                filas = cur.fetchall()
                print(pd.DataFrame.from_records(filas, columns=cols).to_string(index=False), "\n")
            if not cur.nextset():
                break


def tipos_tabla(cx: pyodbc.Connection, tabla: str) -> dict[str, tuple]:
    """Tipos ODBC de cada columna, para que fast_executemany no los deduzca de la primera fila."""
    esquema, nombre = tabla.split(".")
    cur = cx.cursor()
    cur.execute(
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?", esquema, nombre)
    mapa = {
        "tinyint": (pyodbc.SQL_TINYINT, 0, 0), "int": (pyodbc.SQL_INTEGER, 0, 0),
        "bigint": (pyodbc.SQL_BIGINT, 0, 0), "bit": (pyodbc.SQL_BIT, 0, 0),
        "date": (pyodbc.SQL_TYPE_DATE, 0, 0), "datetime2": (pyodbc.SQL_TYPE_TIMESTAMP, 27, 0),
    }
    tipos = {}
    for col, tipo, largo, prec, escala in cur.fetchall():
        if tipo == "decimal":
            tipos[col] = (pyodbc.SQL_DECIMAL, prec, escala)
        elif tipo in ("varchar", "nvarchar"):
            tipos[col] = (pyodbc.SQL_WVARCHAR, largo, 0)
        else:
            tipos[col] = mapa[tipo]
    return tipos


def cargar_csv(cx: pyodbc.Connection, csv: Path, tabla: str) -> None:
    df = pd.read_csv(csv, dtype=str, keep_default_na=False, na_values=[""])
    tipos = tipos_tabla(cx, tabla)

    def convertidor(col: str):
        tipo, _, escala = tipos[col]
        if tipo in (pyodbc.SQL_TINYINT, pyodbc.SQL_INTEGER, pyodbc.SQL_BIGINT, pyodbc.SQL_BIT):
            return lambda v: int(float(v))
        if tipo == pyodbc.SQL_DECIMAL:
            return lambda v: Decimal(v).quantize(Decimal(1).scaleb(-escala))
        if tipo == pyodbc.SQL_TYPE_DATE:
            return date.fromisoformat
        if tipo == pyodbc.SQL_TYPE_TIMESTAMP:
            return datetime.fromisoformat
        return str

    convs = [convertidor(c) for c in df.columns]
    filas = [
        tuple(None if pd.isna(v) else f(v) for f, v in zip(convs, fila))
        for fila in df.itertuples(index=False, name=None)
    ]
    columnas = ", ".join(f"[{c}]" for c in df.columns)
    marcas = ", ".join("?" for _ in df.columns)
    sql = f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})"

    cur = cx.cursor()
    cur.execute(f"TRUNCATE TABLE {tabla}")
    cur.fast_executemany = True
    cur.setinputsizes([tipos[c] for c in df.columns])
    inicio = time.time()
    for i in range(0, len(filas), LOTE):
        cur.executemany(sql, filas[i:i + LOTE])
        print(f"\r  {tabla}: {min(i + LOTE, len(filas)):,}/{len(filas):,} filas", end="", flush=True)
    print(f" ({time.time() - inicio:.0f} s)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--servidor", required=True, help="Host del SQL Server (ej. db12345.public.databaseasp.net)")
    p.add_argument("--base", required=True, help="Nombre de la base de datos")
    p.add_argument("--usuario", required=True, help="Usuario SQL")
    p.add_argument("--driver", default="ODBC Driver 18 for SQL Server",
                   help="Driver ODBC instalado (ver: Orígenes de datos ODBC en Windows)")
    p.add_argument("--conservar-staging", action="store_true",
                   help="No vaciar stg.* al terminar (por defecto se vacía para ahorrar espacio)")
    a = p.parse_args()

    for f in ("stg_incidente.csv", "stg_movilizacion.csv"):
        if not (PROCESADOS / f).exists():
            raise SystemExit(f"Falta data/processed/{f}. Ejecutar antes: python src/etl/etl_lfb.py")

    cx = conectar(a)
    ejecutar_script(cx, SQL / "01_crear_modelo.sql")
    print("\n== Carga del staging")
    cargar_csv(cx, PROCESADOS / "stg_incidente.csv", "stg.Incidente")
    cargar_csv(cx, PROCESADOS / "stg_movilizacion.csv", "stg.Movilizacion")
    ejecutar_script(cx, SQL / "03_poblar_modelo.sql")
    ejecutar_script(cx, SQL / "04_validaciones.sql", mostrar=True)
    if not a.conservar_staging:
        # El staging ocupa ~70 MB; se vacía para ahorrar espacio en el hosting.
        cx.cursor().execute("TRUNCATE TABLE stg.Incidente; TRUNCATE TABLE stg.Movilizacion;")
        print("Staging vaciado (usar --conservar-staging para mantenerlo).")
    cx.close()
    print("Listo: modelo LFB cargado.")


if __name__ == "__main__":
    main()
