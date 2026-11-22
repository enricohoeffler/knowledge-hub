FROM python:3.12-slim
ARG BUILD_VERSION=dev
ARG BUILD_ARCH=amd64
LABEL io.hass.version="${BUILD_VERSION}" \
      io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}"
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py launcher.py smb_storage.py mkdocs-template.yml layout.css ./
COPY fixtures ./fixtures
ENV PYTHONUNBUFFERED=1
CMD ["python", "launcher.py"]
