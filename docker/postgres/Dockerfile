FROM postgres:16

# Install pgvector extension without changing the base Postgres image
RUN apt-get update \
    && apt-get install -y curl gnupg \
    # Add PostgreSQL APT repository for pgvector packages
    && sh -c 'release=$(grep VERSION_CODENAME /etc/os-release | cut -d= -f2) \
      && echo "deb http://apt.postgresql.org/pub/repos/apt ${release}-pgdg main" > /etc/apt/sources.list.d/pgdg.list' \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/postgresql.gpg \
    && apt-get update \
    && apt-get install -y postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*