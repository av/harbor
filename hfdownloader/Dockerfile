# Kitbash docker image for running the HuggingFaceModelDownloader CLI
# https://github.com/bodaay/HuggingFaceModelDownloader

FROM ubuntu:22.04
SHELL ["/bin/bash", "-c"]
RUN apt-get update && apt-get install -y curl

WORKDIR /app
RUN bash <(curl -sSL https://g.bodaay.io/hfd) -h
ENTRYPOINT ["/app/hfdownloader"]
