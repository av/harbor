# syntax=docker/dockerfile:1
# Harbor test row — Debian 12 (bookworm).
#
# Debian 12's `main` does not ship `docker-compose-plugin` or the
# `docker-buildx` binary — we add Docker's official apt repo and pull
# docker-ce + compose-plugin from there. Matches the ubuntu-2204 row.
#
# Inherits the shared daemon.json from harbor-test/base.
FROM harbor-test/base AS harbor-base

FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive
ENV container=docker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        systemd systemd-sysv \
        git jq sudo \
        docker-ce docker-ce-cli containerd.io \
        docker-compose-plugin docker-buildx-plugin \
        fuse-overlayfs uidmap \
        iproute2 iptables \
        nodejs npm \
    && npm install -g httpyac \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN find /etc/systemd/system /lib/systemd/system \
        \( -path '*getty*' -o -path '*lvm2*' -o -path '*networkd-wait*' \) \
        -exec rm -rf {} + \
    && systemctl enable docker.service

RUN mkdir -p /etc/docker /opt/harbor-test/repo /opt/harbor-test/artifacts
COPY --from=harbor-base /daemon.json /etc/docker/daemon.json

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
