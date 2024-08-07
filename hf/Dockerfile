FROM pkgxdev/pkgx

# Install/warmup
RUN pkgx install huggingface-cli
RUN huggingface-cli --help

ENTRYPOINT [ "huggingface-cli" ]