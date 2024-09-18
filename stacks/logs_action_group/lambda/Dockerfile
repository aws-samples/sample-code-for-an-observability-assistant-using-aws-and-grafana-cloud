# FROM public.ecr.aws/lambda/python:3.12
# # WORKDIR /app
# COPY . .
# RUN pip install --upgrade --force-reinstall -r requirements.txt
# # HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health
# CMD [ "app.lambda_handler" ]

FROM python:3.12.5
EXPOSE 80
COPY . .
RUN pip install --no-cache-dir --upgrade -r requirements.txt
HEALTHCHECK CMD curl --fail http://localhost/health
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80"]