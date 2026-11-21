# Usta'yı bir sunucuda (ev sunucusu, DGX) servis olarak çalıştırmak için. Kullanım: docs/docker.md
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 usta
WORKDIR /src
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /src

USER usta
ENV USTA_HOME=/data
WORKDIR /data
EXPOSE 8765
CMD ["usta", "serve", "--host", "0.0.0.0", "--allow-remote"]
