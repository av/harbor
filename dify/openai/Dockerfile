FROM node:20

WORKDIR /dify2openai

COPY . .
RUN npm install

ENTRYPOINT [ "node", "app.js" ]