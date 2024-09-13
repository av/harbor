FROM python:3.11

WORKDIR /app

RUN git clone https://github.com/EleutherAI/lm-evaluation-harness /app
RUN pip install -e ".[hf_transfer,api]"

ENTRYPOINT [ "lm_eval" ]