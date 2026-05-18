# syntax=docker/dockerfile:1
# Harbor test row — Rocky Linux 9.
#
# RHEL-9 family with enterprise release cadence — different from Fedora's
# rolling dnf. Rocky 9's base repos do not ship Docker, so we add Docker's
# official CentOS repo (Rocky is binary-compatible). Node.js 16 is the
# default stream which is too old for modern httpyac; enable the `nodejs:20`
# module stream before install.
#
# Inherits the shared daemon.json from harbor-test/base.
FROM harbor-test/base AS harbor-base

FROM rockylinux/rockylinux:9

ENV container=docker

# curl-minimal is shipped in the base image and satisfies our use; asking
# for `curl` here triggers a conflict because both come from baseos.
RUN dnf -y install dnf-plugins-core ca-certificates \
    && dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo \
    && dnf -y module reset nodejs \
    && dnf -y module enable nodejs:20 \
    && dnf -y install \
        systemd \
        git jq sudo \
        docker-ce docker-ce-cli containerd.io \
        docker-compose-plugin docker-buildx-plugin \
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
