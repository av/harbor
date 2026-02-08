FROM node:20

RUN apt-get update && apt-get install -y git && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone https://github.com/pgibler/cmdh.git && cd cmdh

# Little switcheroo
COPY ./ollama.ts /app/cmdh/src/api/ollama.ts
RUN cd /app/cmdh && ./install.sh
RUN npm i tsx zod zod-to-json-schema

ENTRYPOINT [ "/app/node_modules/.bin/tsx", "/app/cmdh/src/cmdh.ts" ]