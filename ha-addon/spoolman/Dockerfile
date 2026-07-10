# Thin wrapper over the published Spoolman image (#89). Home Assistant passes the matching per-arch
# image from build.yaml as BUILD_FROM. The wrapper only adds a small launcher that maps the add-on
# options to the SPOOLMAN_* environment variables the server reads and persists data under /data.
ARG BUILD_FROM
FROM ${BUILD_FROM}

USER root
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Replace the image's own entrypoint with the launcher (which ultimately execs that entrypoint).
ENTRYPOINT []
CMD ["/run.sh"]
