FROM golang:1.23.1

WORKDIR /app
RUN go install github.com/danielmiessler/fabric@latest

ENTRYPOINT [ "fabric" ]

