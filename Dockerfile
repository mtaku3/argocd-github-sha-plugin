FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv export --no-dev --no-hashes -o requirements.txt && \
    pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y uv && \
    rm requirements.txt

COPY main.py .

RUN useradd -r -u 999 plugin
USER 999
EXPOSE 4355

CMD ["python", "main.py"]
