FROM node:lts

WORKDIR /app
RUN git clone https://github.com/zenoverflow/omnichain && cd omnichain

WORKDIR /app/omnichain
RUN npm install

COPY entrypoint.sh /app/omnichain/entrypoint.sh

ENTRYPOINT [ "/app/omnichain/entrypoint.sh" ]
CMD ["npm", "run", "serve"]