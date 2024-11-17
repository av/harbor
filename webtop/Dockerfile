ARG HARBOR_WEBTOP_IMAGE=lscr.io/linuxserver/webtop
ARG HARBOR_WEBTOP_VERSION=ubuntu-kde

FROM ${HARBOR_WEBTOP_IMAGE}:${HARBOR_WEBTOP_VERSION}

# Extras for desktop agents
RUN sudo apt-get update \
  && sudo apt-get install -y \
  curl \
  jq \
  wget \
  imagemagick \
  at-spi2-core \
  wmctrl \
  libreoffice \
  fonts-noto-cjk \
  neofetch \
  python3-requests \
  python3-numpy \
  python3-pandas \
  python3-matplotlib \
  python3-scipy \
  python3-sklearn \
  python3-reportlab


RUN curl -L https://npmjs.org/install.sh | sh
RUN npm install -g --unsafe-perm yarn
RUN sudo chown -R abc:abc /usr/lib/node_modules

# Pre-provision Harbor
# 1. Install the App
USER abc
RUN LATEST_DEB_URL=$(curl -s "https://api.github.com/repos/av/harbor/releases/latest" | jq -r '.assets[] | select(.name | contains("Harbor") and endswith(".deb")) | .browser_download_url') \
  && mkdir -p /tmp/harbor \
  && wget -O /tmp/harbor/harbor.deb "$LATEST_DEB_URL" \
  && sudo apt-get install -y /tmp/harbor/harbor.deb
# 2. Prepare workspace for the CLI mount
USER root
RUN mkdir /harbor