FROM golang:1.24.4

WORKDIR /app
RUN go install github.com/danielmiessler/fabric@latest

ENTRYPOINT [ "fabric" ]

