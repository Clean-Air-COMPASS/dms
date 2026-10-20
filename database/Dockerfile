FROM postgres:15.19-bookworm@sha256:d4a8e1f88f475ee3e0137fa89d21ebc59f6c6ab16bf369ee92907607cc3455ae

# The same Debian packages are published for amd64 and arm64. Alembic owns
# extension creation so fresh installs and upgrades follow one schema path.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        postgresql-15-postgis-3 \
        postgresql-15-postgis-3-scripts \
    && rm -rf /var/lib/apt/lists/*

COPY compassaq-entrypoint.sh /usr/local/bin/compassaq-entrypoint.sh
RUN chmod +x /usr/local/bin/compassaq-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/compassaq-entrypoint.sh"]
CMD ["postgres"]
