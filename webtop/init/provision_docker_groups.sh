#!/bin/bash

log() {
  if [ "$HARBOR_LOG_LEVEL" == "DEBUG" ]; then
    echo "[harbor-init] $1"
  fi
}

log "Provisioning docker groups"
sudo groupadd -g 999 docker-ubuntu
sudo groupadd -g 992 docker-lsio
sudo groupadd -g 130 docker-plex

log "Adding lsio user to docker groups"
sudo usermod -aG docker-ubuntu abc
sudo usermod -aG 999 abc

sudo usermod -aG docker-lsio abc
sudo usermod -aG 992 abc

sudo usermod -aG docker-plex abc
sudo usermod -aG 130 abc