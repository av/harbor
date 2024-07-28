FROM cimg/node:lts

WORKDIR /app
RUN mkdir -p ~/workspace

COPY package.json package-lock.json /app/
RUN npm install

COPY /src /app/src

ENTRYPOINT [ "npm", "run", "--silent", "cli", "--" ]
