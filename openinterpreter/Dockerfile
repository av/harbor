FROM pkgxdev/pkgx

RUN pkgx install python@3.11 pipx openssl
RUN pipx install open-interpreter

RUN echo 'export LD_LIBRARY_PATH=$(find / -name "*.so" -exec dirname {} \; | sort -u | tr "\n" ":" | sed '\''s/:$//'\'')"${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"' >> ~/.bashrc
RUN interpreter --version

ENTRYPOINT [ "bash", "-c", "interpreter" ]