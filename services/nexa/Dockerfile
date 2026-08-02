ARG HARBOR_NEXA_IMAGE=ubuntu:24.04

FROM ${HARBOR_NEXA_IMAGE}

# Last NexaAI-branded release with Linux x86_64 assets.
# Later tags (v0.3.x) are the Qualcomm "GenieX" rebrand and
# ship Snapdragon/ARM64-only builds.
ARG HARBOR_NEXA_VERSION=v0.2.73

RUN apt-get update \
  # libgomp1 is required by the bundled llama.cpp CPU backend,
  # libvulkan1 by the Vulkan GPU backend
  && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 libvulkan1 \
  && rm -rf /var/lib/apt/lists/*

# Self-contained installer with an embedded binary payload;
# installs to /opt/nexa_sdk and symlinks /usr/local/bin/nexa.
# Download and run in separate steps so a failed download
# fails the build instead of piping nothing into sh.
RUN curl -fsSL "https://github.com/NexaAI/nexa-sdk/releases/download/${HARBOR_NEXA_VERSION}/nexa-cli_linux_x86_64.sh" \
  -o /tmp/nexa-install.sh \
  && bash /tmp/nexa-install.sh \
  && rm -f /tmp/nexa-install.sh \
  && command -v nexa

COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT [ "/entrypoint.sh" ]
