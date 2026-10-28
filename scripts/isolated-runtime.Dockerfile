FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app
COPY broker /app/broker
COPY owner_agent /app/owner_agent
COPY shared /app/shared
COPY dist/owner /app/dist/owner
COPY evidence/sample-proof.json /app/evidence/sample-proof.json
COPY scripts/container_entry.py scripts/owner_ingress.py scripts/verify_living_evidence.py /app/scripts/
USER 1000:1000
ENTRYPOINT ["python", "-m", "scripts.container_entry"]
