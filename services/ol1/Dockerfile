FROM python:3.11

WORKDIR /app
RUN pip install python-dotenv streamlit requests

# Upstream https://github.com/tcsenpai/ol1 was deleted;
# Harbor ships its own adjusted app.py (also bind-mounted at runtime)
COPY app.py /app/app.py

ENTRYPOINT [ "streamlit", "run", "app.py" ]
