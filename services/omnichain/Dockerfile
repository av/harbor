FROM node:lts

RUN apt-get update && apt-get install -y --no-install-recommends socat && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone https://github.com/zenoverflow/omnichain && cd omnichain

WORKDIR /app/omnichain
RUN npm install

COPY entrypoint.sh /app/omnichain/entrypoint.sh

ENTRYPOINT [ "/app/omnichain/entrypoint.sh" ]
CMD ["npm", "run", "serve"]