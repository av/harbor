FROM python:3.11

WORKDIR /app
RUN git clone https://github.com/tcsenpai/ol1 /app
RUN pip install python-dotenv streamlit requests

ENTRYPOINT [ "streamlit", "run", "app.py" ]