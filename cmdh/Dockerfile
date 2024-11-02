FROM pkgxdev/pkgx

WORKDIR /app

RUN pkgx install node@20 npm git
RUN git clone https://github.com/pgibler/cmdh.git && cd cmdh

# Little switcheroo
COPY ./ollama.ts /app/cmdh/src/api/ollama.ts

RUN cd /app/cmdh && ./install.sh
# Warm up pkgx
RUN pkgx /app/cmdh/dist/src/system.js
# RUN ls /app/cmdh
ENTRYPOINT [ "node", "/app/cmdh/dist/src/cmdh.js" ]