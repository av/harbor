#!/bin/sh
set -e

# Copy the configuration file to a writable location
cp /etc/envoy/envoy.yaml /tmp/envoy.yaml

# See original file here:
# https://github.com/bionic-gpt/bionic-gpt/blob/main/.devcontainer/envoy.yaml
# It specifies host names that Harbor needs to override,
# hence we also have to reconfigure Bionic GPT's Envoy with the
# new service names.

# Use sed to replace the addresses in the copied configuration file
sed -i 's/address: app/address: bionicgpt-app/' /tmp/envoy.yaml
sed -i 's/address: barricade/address: bionicgpt-barricade/' /tmp/envoy.yaml

# Start Envoy with the modified configuration
/usr/local/bin/envoy -c /tmp/envoy.yaml