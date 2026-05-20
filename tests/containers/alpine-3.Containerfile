# syntax=docker/dockerfile:1
# Harbor test row — Alpine 3 (musl libc + BusyBox coreutils).
#
# Alpine uses OpenRC, not systemd. We run PID 1 as `/sbin/init` (OpenRC's
# init) and start docker through `rc-service` rather than `systemctl`.
# The orchestrator detects this row by name and adapts the readiness probe.
#
# Inherits the shared daemon.json from harbor-test/base.
FROM harbor-test/base AS harbor-base

FROM alpine:3

RUN apk add --no-cache \
        openrc \
        ca-certificates curl git jq bash sudo \
        docker docker-compose docker-cli-buildx \
        fuse-overlayfs \
        iproute2 iptables \
        nodejs npm \
    && npm install -g httpyac

# OpenRC housekeeping: remove bits that expect real hardware, enable docker.
RUN sed -i 's/^tty/# tty/' /etc/inittab \
    && rc-update add docker default \
    && mkdir -p /run/openrc \
    && touch /run/openrc/softlevel

RUN mkdir -p /etc/docker /opt/harbor-test/repo /opt/harbor-test/artifacts
COPY --from=harbor-base /daemon.json /etc/docker/daemon.json

# OpenRC's supervision init.
CMD ["/sbin/init"]
