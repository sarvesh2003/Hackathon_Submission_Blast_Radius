# Blast Radius selector. Built by the scorer on linux/amd64; runs with no network.
# The base image is the one every commit was labeled in (kept by digest).
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock

# sqlglot at the pinned commit, from its own repository (allowed download).
ADD https://github.com/tobymao/sqlglot/archive/eb11aec4be8cb2122afe713a4816662c3f0fb2fa.tar.gz /opt/sqlglot.tar.gz
RUN cd /opt && tar xzf sqlglot.tar.gz && rm sqlglot.tar.gz \
 && mv sqlglot-eb11aec4be8cb2122afe713a4816662c3f0fb2fa sqlglot

COPY br /app/br
COPY maps /app/maps

ENV SKIP_INTEGRATION=0 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app
# Precompile the pristine sources and our code, and make everything readable by nobody.
RUN python -m compileall -q /opt/sqlglot/sqlglot /opt/sqlglot/tests /app/br \
 && chmod -R a+rX /opt/sqlglot /app

WORKDIR /app
CMD ["python", "-m", "br.main"]
