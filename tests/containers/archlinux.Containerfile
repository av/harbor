# syntax=docker/dockerfile:1
# Harbor test row — Arch Linux (rolling).
#
# Rolling-release distro: catches breakage from bleeding-edge package
# versions before they reach other rows. pacman is the package manager.
# iptables-nft is the default on modern Arch (iptables-legacy was dropped),
# matching our Fedora-43 fix and working on kernels without `ip_tables`.
#
# Inherits the shared daemon.json from harbor-test/base.
FROM harbor-test/base AS harbor-base

FROM archlinux:latest

ENV container=docker

RUN pacman -Syu --noconfirm \
    && pacman -S --noconfirm --needed \
        systemd \
        ca-certificates curl git jq sudo \
        docker docker-compose docker-buildx \
        fuse-overlayfs \
        iproute2 iptables-nft \
        nodejs npm \
    && npm install -g httpyac \
    && pacman -Scc --noconfirm

RUN find /etc/systemd/system /lib/systemd/system \
        \( -path '*getty*' -o -path '*lvm2*' -o -path '*networkd-wait*' \) \
        -exec rm -rf {} + \
    && systemctl enable docker.service

RUN mkdir -p /etc/docker /opt/harbor-test/repo /opt/harbor-test/artifacts
COPY --from=harbor-base /daemon.json /etc/docker/daemon.json

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
