FROM python:3.12-slim

# Unprivileged user: the service only needs network access, not host access.
RUN groupadd --gid 10001 hubapi && useradd --uid 10001 --gid 10001 --no-create-home hubapi

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# rules/*.yaml se leen en el arranque (app/core/rules.py) y el servicio ABORTA si
# faltan. Sin este COPY el contenedor no subiria aunque el codigo este bien: solo
# se copiaba ./app. Son archivos de lectura; el usuario no privilegiado basta.
COPY rules ./rules

USER hubapi
EXPOSE 8091

# Single worker on purpose. The webhook dedupe cache is in-process; running several
# workers would multiply it and let duplicates through. Scale by replicating with a
# shared store (Redis or a unique-constraint table), not with --workers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8091", "--workers", "1"]
