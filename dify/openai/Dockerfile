FROM pkgxdev/pkgx

WORKDIR /dify2openai

# Install + warmup
RUN pkgx install node@20 npm
RUN node --version && npm --version

COPY . .
RUN npm install

ENTRYPOINT [ "node", "app.js" ]