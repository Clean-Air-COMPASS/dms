FROM python:3.11-slim

WORKDIR /app


ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1


RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*


COPY backend/requirements.txt .
COPY backend/plugins/max_value ./plugins/max_value
RUN pip install --no-cache-dir -r requirements.txt



COPY backend/ .
COPY frontend/package.json ./application-package.json

ARG COMPASSAQ_BUILD_SHA
RUN python -c "import datetime,json,os,re; sha=os.environ.get('COMPASSAQ_BUILD_SHA',''); json.dump({'commit_sha': sha if re.fullmatch('[0-9a-f]{40}',sha) else None, 'build_time_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')},open('build-metadata.json','w'))"



RUN printf '#!/bin/sh\nexec python "$@"\n' > /usr/local/bin/py \
    && chmod +x /usr/local/bin/py
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000


ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
