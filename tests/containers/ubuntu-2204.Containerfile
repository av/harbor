# syntax=docker/dockerfile:1
# Harbor test row — Ubuntu 22.04 LTS.
#
# Ubuntu 22.04's own universe does not ship `docker-compose-plugin` or
# `docker-buildx`, so we add Docker's official apt repo and pull docker-ce +
# compose-plugin from there. 24.04 ships these in-repo and uses the simpler
# distro-native path — keeping these two rows different is deliberate: each
# row reflects what a real user on that distro would actually install.
#
# Inherits the shared daemon.json from harbor-test/base.
FROM harbor-test/base AS harbor-base

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV container=docker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    # Docker's official apt repo (docker-compose-plugin is not in jammy's
    # universe). The GPG key is stored in /etc/apt/keyrings/ per the
    # modern deb convention rather than the deprecated apt-key.
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu jammy stable" \
        > /etc/apt/sources.list.d/docker.list \
    # Ubuntu 22.04 jammy ships Node.js 12 — too old for modern httpyac
    # (which uses optional chaining). Pull Node.js 20 from NodeSource.
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && chmod a+r /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        systemd systemd-sysv \
        git jq sudo \
        docker-ce docker-ce-cli containerd.io \
        docker-compose-plugin docker-buildx-plugin \
        fuse-overlayfs uidmap \
        iproute2 iptables \
        nodejs \
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
