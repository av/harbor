FROM pkgxdev/pkgx

WORKDIR /app

RUN pkgx +node@20 npm install qrcode-terminal
COPY ./gen.ts /app/gen.ts
# Activate pkgx env
RUN pkgx gen.ts test

ENTRYPOINT [ "pkgx", "gen.ts" ]