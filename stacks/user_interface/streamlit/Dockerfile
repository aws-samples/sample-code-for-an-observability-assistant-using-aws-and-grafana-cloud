# app/Dockerfile

# FROM python:3.9-slim
FROM public.ecr.aws/lambda/python:3.12
EXPOSE 8501
USER streamlit
COPY . .
RUN pip install --upgrade --force-reinstall -r requirements.txt
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health
ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]