FROM denoland/deno

WORKDIR /app

COPY ./gen.ts /app/gen.ts
RUN deno cache /app/gen.ts

ENTRYPOINT [ "deno", "gen.ts" ]