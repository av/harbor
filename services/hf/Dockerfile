FROM python:3.11

RUN pip install -U huggingface_hub[cli] hf_transfer

COPY entrypoint.sh /harbor-entrypoint.sh
RUN chmod +x /harbor-entrypoint.sh

ENTRYPOINT [ "/harbor-entrypoint.sh" ]
