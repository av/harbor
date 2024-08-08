FROM pkgxdev/pkgx

WORKDIR /app

# pkgx install && warm up
RUN pkgx install git pipx python ffmpeg
RUN python --version && pipx --version && ffmpeg -version

RUN git clone https://github.com/danielmiessler/fabric.git
RUN echo 'export LD_LIBRARY_PATH=$(find / -name "*.so" -exec dirname {} \; | sort -u | tr "\n" ":" | sed '\''s/:$//'\'')"${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"' >> ~/.bashrc

WORKDIR /app/fabric

RUN pipx install .
RUN fabric --help

COPY start_fabric.sh /app/fabric/start_fabric.sh

ENTRYPOINT ["bash", "/app/fabric/start_fabric.sh"]

