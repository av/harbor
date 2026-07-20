FROM alpine

RUN apk update
RUN apk add bash
RUN apk add curl
# plandex.ai no longer resolves; fetch the installer from the repo instead
RUN wget https://raw.githubusercontent.com/plandex-ai/plandex/main/app/cli/install.sh
# The installer resolves the version from plandex.ai (also dead) unless
# PLANDEX_VERSION is set — derive it from the latest GitHub release instead
RUN PLANDEX_VERSION=$(wget -qO- https://api.github.com/repos/plandex-ai/plandex/releases/latest | grep -o '"tag_name": *"cli/v[^"]*"' | sed 's#.*cli/v##; s/"$//') bash install.sh

ENTRYPOINT plandex