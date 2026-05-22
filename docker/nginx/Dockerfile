FROM nginx:1.27-alpine@sha256:5a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b

# Main config (static — no port values)
COPY docker/nginx/nginx.conf /etc/nginx/nginx.conf

# Template processed at startup by the nginx image's entrypoint via envsubst.
# Substitutes ${LOCALSTACK_PORT}, ${OPENSEARCH_PORT}, ${OPENSEARCH_DASHBOARDS_PORT}
# and writes the result to /etc/nginx/conf.d/default.conf.
COPY docker/nginx/templates/ /etc/nginx/templates/

COPY docker/nginx/error_pages/ /usr/share/nginx/html/errors/
