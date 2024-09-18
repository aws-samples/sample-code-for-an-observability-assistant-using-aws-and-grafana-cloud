from fastapi import FastAPI, Query, Body
from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit
# import logging
import requests
from requests.exceptions import HTTPError
from aws_lambda_powertools.utilities import parameters
import os
from typing_extensions import Annotated

app = FastAPI()
app.openapi_version = "3.0.0"
tracer = Tracer()
logger = Logger()

metrics = Metrics(namespace="LogsLambdaAgent")
secretsmanager = parameters.SecretsProvider()

# Methond gets the environment variables from OS
def get_env_var(var_name):
    try:
        return os.environ[var_name]
    except KeyError:
        logger.error(f"Environment variable {var_name} is not set.")
        return None
    
@app.get("/health", include_in_schema=False)
def health_check():
    return {"status": "healthy"}

@app.get("/invoke-logql", 
         summary="Invokes a given logql statement",
         description="Makes GET HTTP to Grafana Cloud to invoke a specified logql statement passed in the input .This calls \
         /loki/api/v1/query_range endpoint from Grafana Loki host endpoint using basic authentication.\
         Secrets to call are stored in AWS Secrets Manager",
         operation_id="invokeLogqlStatement",
         tags=["GrafanaCloud","Loki","Statement"],
         response_description="LogQL Statement invocation results from Grafana Cloud"
         )
@tracer.capture_method
def invoke_logql_statement(
    logql: Annotated[str, Query(description="The LogQL Statement to invoke", strict=True)]
) -> Annotated[dict, Body(description="Results from the logql statement")]:
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="LogQLInvocations", unit=MetricUnit.Count, value=1)   
    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/loki/api/v1/query_range"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])
        # Using this because directly accessing the promql input is truncating the records after comma
        # This does bypass the typing extension validation, but good enough to generate the openapi spec
        # without compromising 
        print(app.current_event.parameters[0]['value'])
        session.params = {
            'query': app.current_event.parameters[0]['value'],
            'limit': 5000
        }
        logger.debug(session.params)
        response = session.get(base_url).json()
        return response
    except Exception as e:
        logger.error(str(e))
        raise 
    
@app.get("/get-available-logql-labels", 
         summary="Get available LogQL filter labels from Grafana Cloud",
         description="Makes GET HTTP to Grafana Cloud to get a list of available filter labels .This calls \
         /loki/api/v1/labels from Grafana Loki host endpoint using basic authentication.\
         Secrets to call are stored in AWS Secrets Manager",
         operation_id="getAvailableLokiLabels",
         tags=["GrafanaCloud","Loki","Labels"],
         response_description="List of available Loki labels from Grafana Cloud"
         )
@tracer.capture_method
def get_available_labels() -> Annotated[dict, Body(description="List of available Loki Labels from Grafana Cloud")]:
    # Adding custom logs
    logger.debug("get_available_labels - Invoked")
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="GetAvailableLabelsInvocations", unit=MetricUnit.Count, value=1)

    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/loki/api/v1/labels"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])   
        
        response = session.get(base_url).json()
        logger.info("get_available_labels - HTTP 200")
        #append status code in the response
        logger.info(response)
        logger.info(type(response))
        return response
    except Exception as e:
        logger.error(str(e))
        raise 
