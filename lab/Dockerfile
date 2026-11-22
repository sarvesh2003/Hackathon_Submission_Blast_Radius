# Local lab image (never submitted): the environment the labels were made in.
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock \
 && pip install --no-cache-dir --no-deps coverage==7.10.7
ADD https://github.com/tobymao/sqlglot/archive/eb11aec4be8cb2122afe713a4816662c3f0fb2fa.tar.gz /opt/sqlglot.tar.gz
RUN cd /opt && tar xzf sqlglot.tar.gz && mv sqlglot-eb11aec4be8cb2122afe713a4816662c3f0fb2fa sqlglot && rm sqlglot.tar.gz \
 && python -m compileall -q /opt/sqlglot/sqlglot /opt/sqlglot/tests && chmod -R a+rX /opt/sqlglot
ENV PYTHONPATH=/opt/sqlglot SKIP_INTEGRATION=0 PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/sqlglot
