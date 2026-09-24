# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        freetds-dev \
        libkrb5-dev \
        libpq-dev \
        libxml2-dev \
        libxmlsec1-dev \
        libxslt1-dev \
        pkg-config \
        unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install --no-cache-dir \
        poetry==2.2.1 poetry-plugin-export

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY poetry.lock pyproject.toml build-constraints.txt ./
RUN /opt/poetry/bin/poetry export --only main --without-hashes \
        --output requirements.txt \
    && sed -i '/^pymssql==/d' requirements.txt \
    && pip install --no-cache-dir --constraint build-constraints.txt \
        Cython setuptools-scm wheel \
    && pip install --no-cache-dir --no-build-isolation pymssql==2.2.7 \
    && pip install --no-cache-dir --requirement requirements.txt \
    && pip uninstall --yes Cython setuptools-scm vcs-versioning


FROM python:3.11-slim-bookworm AS runtime-base

# PYTHONPATH makes the package importable from any working directory, as the
# previous `poetry install --only-root` did.
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/fleetmanager \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        curl \
        libgssapi-krb5-2 \
        libkrb5-3 \
        libmariadb3 \
        libpq5 \
        libsybdb5 \
        libxml2 \
        libxmlsec1-openssl \
        libxslt1.1 \
        unixodbc \
    && curl --fail --silent --show-error --location \
        https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
        --output /tmp/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    # The DSN uses ODBC Driver 17, which the previous image got through
    # mssql-tools. Microsoft only publishes it for amd64 on Debian 12.
    && if [ "$(dpkg --print-architecture)" = amd64 ]; then odbc17=msodbcsql17; else odbc17=; fi \
    && ACCEPT_EULA=Y apt-get install --yes --no-install-recommends msodbcsql18 $odbc17 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 fleetoptimiser \
    && useradd --system --uid 10001 --gid fleetoptimiser \
        --home-dir /fleetmanager --shell /usr/sbin/nologin fleetoptimiser

WORKDIR /fleetmanager

COPY --from=builder /opt/venv /opt/venv
COPY --chown=fleetoptimiser:fleetoptimiser --exclude=tests fleetmanager ./fleetmanager

RUN mkdir -p /fleetmanager/running_tasks \
    && chown fleetoptimiser:fleetoptimiser /fleetmanager/running_tasks

USER 10001:10001


# Built explicitly with `--target test` in CI; skipped by the default build.
FROM runtime-base AS test

ENV ALLOW_IN_MEMORY_DATABASE=true

# tests write export files to the working directory
USER root
COPY --chown=fleetoptimiser:fleetoptimiser fleetmanager/tests ./fleetmanager/tests
RUN pytest fleetmanager/tests/


FROM runtime-base AS runtime

EXPOSE 3001

CMD ["uvicorn", "fleetmanager:api.app", "--port", "3001", "--host", "0.0.0.0", "--proxy-headers", "--root-path", "/api", "--workers", "2"]
