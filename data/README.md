# Datos oficiales del proyecto

La carga final usa los incidentes y las movilizaciones de London Fire Brigade de 2021 a 2025. Los originales abarcan más años. El script selecciona el periodo con el campo `CalYear`.

| Archivo usado en la carga | Cobertura del original | Fuente |
|---|---|---|
| [incidentes_2018_2023.xlsx](https://github.com/taniaa03/London/releases/download/datos-2021-2025/incidentes_2018_2023.xlsx) | 2018 a 2023 | [London Datastore](https://data.london.gov.uk/download/em8xy/f5066d66-c7a3-415f-9629-026fbda61822/LFB%20Incident%20data%20from%202018%20-%202023.xlsx) |
| [incidentes_2024_hasta_julio_2026.xlsx](https://github.com/taniaa03/London/releases/download/datos-2021-2025/incidentes_2024_hasta_julio_2026.xlsx) | 2024 a julio de 2026 | [London Datastore](https://data.london.gov.uk/download/em8xy/58m/LFB%20Incident%20data%20from%202024%20onwards.xlsx) |
| [movilizaciones_2021_2024.csv](https://github.com/taniaa03/London/releases/download/datos-2021-2025/movilizaciones_2021_2024.csv) | 2021 a 2024 | [London Datastore](https://data.london.gov.uk/download/24r65/3ff29fb5-3935-41b2-89f1-38571059237e/LFB%20Mobilisation%20data%20from%202021%20-%202024.csv) |
| [movilizaciones_2025_hasta_julio_2026.csv](https://github.com/taniaa03/London/releases/download/datos-2021-2025/movilizaciones_2025_hasta_julio_2026.csv) | 2025 a julio de 2026 | [London Datastore](https://data.london.gov.uk/download/24r65/7d5b4e2f-3ddb-48b9-8a4d-bf86bdf6a4ef/LFB%20Mobilisation%20data%20from%202025.csv) |

## Cargar los datos

1. Descarga los cuatro archivos de la primera columna y guárdalos con sus nombres en `data/originales/`.
2. Crea la base vacía `LondonFireBrigadeDM` en SQL Server. El script se conecta a la instancia local `.\SQLEXPRESS` con autenticación de Windows y el controlador ODBC 18 de Microsoft.
3. Desde la raíz del repositorio, instala las dependencias y ejecuta la carga.

    ~~~powershell
    python -m pip install "pandas>=2.2,<4" "pyodbc>=5,<6" "python-calamine>=0.2,<1"
    python src/poblar_datamart.py
    ~~~

[Script de carga](../src/poblar_datamart.py) · [Diccionario de fuentes](../docs/04_Diccionario_datos/Diccionario_fuentes.md) · [Historial de descargas](manifest_descargas.json)

Metadatos de [incidentes](../docs/04_Diccionario_datos/metadatos/diccionario_incidentes.xlsx) y [movilizaciones](../docs/04_Diccionario_datos/metadatos/diccionario_movilizaciones.xlsx).

Source: London Fire Brigade / London Datastore. Contains public sector information licensed under the [Open Government Licence v2.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/2/).
