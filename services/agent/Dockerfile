ARG HARBOR_AGENT_IMAGE=lscr.io/linuxserver/webtop
ARG HARBOR_AGENT_VERSION=ubuntu-kde

FROM ${HARBOR_AGENT_IMAGE}:${HARBOR_AGENT_VERSION}

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
  python3-pip \
  python3-requests \
  python3-numpy \
  python3-pandas \
  python3-matplotlib \
  python3-scipy \
  python3-sklearn \
  python3-reportlab \
  && rm -rf /var/lib/apt/lists/*

RUN curl -L https://npmjs.org/install.sh | sh
RUN npm install -g --unsafe-perm yarn
RUN sudo chown -R abc:abc /usr/lib/node_modules

# This is an alternative for CMD, as Webtop has
# its own set of commands to start and maintain
COPY /docker/services.d /custom-services.d

# Add the agent sources
WORKDIR /config/agent
COPY requirements.txt /config/agent/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --break-system-packages
COPY /src /config/agent/src
WORKDIR /config/agent/src