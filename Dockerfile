# Build stage for PDM dependencies
FROM python:3.10-slim AS pdm

ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
RUN apt update
RUN apt install -y gcc build-essential git

WORKDIR /app

# Install PDM
RUN pip install -U pip setuptools wheel && \
    pip install pdm

# Copy project files for dependency installation
COPY pyproject.toml pdm.lock ./

# Install production dependencies
RUN --mount=type=cache,target=/root/.cache/pdm pdm install --prod --frozen-lockfile --no-editable

# Final stage
FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

ENV PUID=65534
ENV PGID=65534
ENV UMASK_SET=022

# Create non-root user
RUN set -e \
    && getent group nogroup || groupadd -g ${PGID} nogroup \
    && getent passwd nobody || useradd -u ${PUID} -g nogroup -s /bin/bash -m nobody

# Install runtime dependencies
RUN apt update && apt install -y curl unzip \
    && curl https://rclone.org/install.sh | bash \
    && if [ "$(uname -m)" = "x86_64" ]; then ARCH=amd64; elif [ "$(uname -m)" = "aarch64" ]; then ARCH=arm64; fi \
    && curl https://dl.min.io/client/mc/release/linux-${ARCH}/mc --create-dirs -o /usr/bin/mc \
    && chmod +x /usr/bin/mc \
    && rm -rf /tmp/* /var/lib/apt/lists/*

# Set environment variables
ENV LANG="C.UTF-8" \
    TZ="Asia/Shanghai" \
    NASTOOL_CONFIG="/config/config.yaml" \
    NASTOOL_AUTO_UPDATE=true \
    NASTOOL_CN_UPDATE=true \
    NASTOOL_VERSION=master \
    PS1="\u@\h:\w \$ " \
    WORKDIR="/nastool" \
    PYTHONPATH="/app/.venv/lib/python3.10/site-packages" \
    VIRTUAL_ENV="/app/.venv" \
    PATH="/app/.venv/bin:$PATH"

WORKDIR ${WORKDIR}

# Copy dependencies from pdm stage
COPY --from=pdm /app/.venv /app/.venv

# Configure system
RUN ln -sf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo "${TZ}" > /etc/timezone \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && echo 'fs.inotify.max_user_watches=524288' >> /etc/sysctl.conf \
    && echo 'fs.inotify.max_user_instances=524288' >> /etc/sysctl.conf \
    && mkdir -p /config

COPY ./src /nastool

# Change ownership of application files
RUN chown -R nobody:nogroup ${WORKDIR} \
      && chown -R nobody:nogroup /config

# Switch to non-root user
USER nobody

EXPOSE 3000
VOLUME ["/config"]
CMD ["python", "run.py"]
