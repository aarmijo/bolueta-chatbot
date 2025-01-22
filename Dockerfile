# ====================================
# Build the frontend
# ====================================
FROM node:20 AS frontend

WORKDIR /app/frontend

COPY .frontend /app/frontend

RUN npm install --legacy-peer-deps && npm run build


# ====================================
# Backend
# ====================================
FROM python:3.11 AS build

WORKDIR /app

ENV PYTHONPATH=/app

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | POETRY_VERSION=2.0.1 POETRY_HOME=/opt/poetry python && \
    cd /usr/local/bin && \
    ln -s /opt/poetry/bin/poetry && \
    poetry config virtualenvs.create false

# Install Chromium for web loader
# Can disable this if you don't use the web loader to reduce the image size
RUN apt update && apt install -y chromium chromium-driver

# Install dependencies
COPY ./pyproject.toml ./poetry.lock* /app/
RUN poetry install --no-root --no-cache --only main

# ====================================
# Release
# ====================================
FROM build AS release

COPY . .

COPY --from=frontend /app/frontend/out /app/static

# Remove frontend code
RUN rm -rf .frontend

EXPOSE 8000

# Generate index
RUN poetry run generate > ./index.log 2>&1

#CMD ["sleep", "1d"]
#CMD ["sh", "-c", "poetry run prod 2>&1 | tee ./poetry_run_prod.log"]
CMD ["poetry", "run", "prod"]
