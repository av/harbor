FROM busybox:1.35.0-uclibc as busybox
COPY --from=ghcr.io/charmbracelet/gum /usr/local/bin/gum /usr/local/bin/gum

ENTRYPOINT [ "/usr/local/bin/gum" ]