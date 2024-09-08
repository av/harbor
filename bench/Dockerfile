FROM denoland/deno:1.46.3

WORKDIR /app
COPY src/ /app/src
RUN deno cache src/deps.ts

ENTRYPOINT ["deno", "run", "-A", "src/bench.ts"]