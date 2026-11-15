FROM python:3.12-slim-bookworm

WORKDIR /app/bi_dashboards
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libgssapi-krb5-2 \
    && curl -fsSLo /tmp/ms-repo.deb https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i /tmp/ms-repo.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/* /tmp/ms-repo.deb

COPY bi_dashboards/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY bi_dashboards/dashboard.py bi_dashboards/consulta_sql.py bi_dashboards/filtro_subgrupo.py ./
COPY bi_dashboards/actividad_horaria.py bi_dashboards/analisis_llegada.py bi_dashboards/analisis_municipal.py ./
COPY bi_dashboards/analisis_costos.py bi_dashboards/analisis_despliegue.py bi_dashboards/analisis_prevencion.py bi_dashboards/estaciones_mapa.py ./
COPY bi_dashboards/perfil_incidentes.py ./
COPY bi_dashboards/assets ./assets
COPY data/README.md /app/data/README.md
COPY docs/04_Diccionario_datos/Diccionario_modelo.md /app/docs/04_Diccionario_datos/Diccionario_modelo.md

ENV PYTHONUNBUFFERED=1 PORT=8050
EXPOSE 8050
CMD ["sh", "-c", "exec gunicorn dashboard:server --bind 0.0.0.0:$PORT --threads 4 --timeout 90"]
