FROM python:3.11
SHELL ["/bin/bash", "-c"]

WORKDIR /app
RUN pip install pyyaml

RUN curl https://zyedidia.github.io/eget.sh | sh
RUN ./eget sigoden/aichat

ENTRYPOINT [ "/app/aichat" ]