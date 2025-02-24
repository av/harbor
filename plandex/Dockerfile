FROM alpine

RUN apk update
RUN apk add bash
RUN apk add curl
RUN wget https://plandex.ai/install.sh
RUN bash install.sh

ENTRYPOINT plandex