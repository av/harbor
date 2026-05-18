# syntax=docker/dockerfile:1
# Harbor test row — Fedora 43.
#
# Fedora ships Moby (docker-ce compatible) as `moby-engine`, with
# `docker-compose` providing v2 plugin semantics. systemd is first-class.
#
# Inherits the shared daemon.json from harbor-test/base.
FROM harbor-test/base AS harbor-base

FROM fedora:43

ENV container=docker

# Fedora 43 kernels no longer ship the legacy `ip_tables` module, so the
# legacy iptables userspace can't modprobe it and nested dockerd's NAT
# bridge setup fails. Install `iptables-nft` (not `-legacy`); on Fedora the
# alternatives system then points /usr/sbin/iptables at the nft backend by
# default, so dockerd speaks nftables and comes up cleanly.
RUN dnf -y install \
        systemd \
        ca-certificates curl git jq sudo \
        moby-engine docker-compose \
        fuse-overlayfs shadow-utils \
        iproute iptables-nft \
        nodejs npm \
    && npm install -g httpyac \
    && dnf clean all

RUN find /etc/systemd/system /lib/systemd/system \
        \( -path '*getty*' -o -path '*networkd-wait*' \) \
        -exec rm -rf {} + \
    && systemctl enable docker.service

RUN mkdir -p /etc/docker /opt/harbor-test/repo /opt/harbor-test/artifacts
COPY --from=harbor-base /daemon.json /etc/docker/daemon.json

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
