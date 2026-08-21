FROM python:3-alpine

RUN adduser -D navidromster
USER navidromster
WORKDIR /app
COPY app.py .

ENV PORT=8000
EXPOSE 8000
CMD ["python", "app.py"]
