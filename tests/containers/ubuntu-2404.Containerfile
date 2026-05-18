# syntax=docker/dockerfile:1
# Harbor test row — Ubuntu 24.04 LTS.
#
# Primary supported target. systemd + nested dockerd + fuse-overlayfs.
#
# Inherits the shared daemon.json from harbor-test/base (see
# tests/containers/base.Containerfile). The orchestrator builds the base
# image before any row.
FROM harbor-test/base AS harbor-base

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV container=docker

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        systemd systemd-sysv \
        ca-certificates curl git jq sudo \
        docker.io docker-compose-v2 docker-buildx \
        fuse-overlayfs uidmap \
        iproute2 iptables \
        nodejs npm \
    && npm install -g httpyac \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# systemd hardening inside container: disable units that fight PID 1 when no
# real hardware is attached. Keeps the boot fast and silent.
RUN find /etc/systemd/system /lib/systemd/system \
        \( -path '*getty*' -o -path '*lvm2*' -o -path '*networkd-wait*' \) \
        -exec rm -rf {} + \
    && systemctl enable docker.service

RUN mkdir -p /etc/docker /opt/harbor-test/repo /opt/harbor-test/artifacts
COPY --from=harbor-base /daemon.json /etc/docker/daemon.json

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
