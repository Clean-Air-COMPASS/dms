FROM python:3.11-slim

WORKDIR /app


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt



COPY . .



RUN mkdir -p /app/qaqc/plugins_local_seed \
    && cp -a /app/qaqc/plugins_local/. /app/qaqc/plugins_local_seed/



RUN printf '#!/bin/sh\nexec python "$@"\n' > /usr/local/bin/py \
    && chmod +x /usr/local/bin/py
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000


ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
