FROM pkgxdev/pkgx

# Install required packages
RUN pkgx install python@3.11 pipx openssl && \
    pipx install parllama

RUN echo 'export LD_LIBRARY_PATH=$(find / -name "*.so" -exec dirname {} \; | sort -u | tr "\n" ":" | sed '\''s/:$//'\'')"${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"' >> ~/.bashrc

CMD parllama