FROM odoo:19.0

USER root
COPY pyproject.toml /tmp/pkg/pyproject.toml
RUN pip install --no-cache-dir --break-system-packages --no-build-isolation --ignore-installed '/tmp/pkg[scripts,dev]'
USER odoo
