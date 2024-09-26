from fastapi import FastAPI, Query, Body
# from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit
import logging
import requests
from requests.exceptions import HTTPError
from aws_lambda_powertools.utilities import parameters
import os,sys
from typing_extensions import Annotated
requests.packages.urllib3.add_stderr_logger() 
app = FastAPI()
app.openapi_version = "3.0.0"
app.title = "ReturnOfControlApis"
tracer = Tracer()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
stream_handler = logging.StreamHandler(sys.stdout)
log_formatter = logging.Formatter("%(asctime)s [%(processName)s: %(process)d] [%(threadName)s: %(thread)d] [%(levelname)s] %(name)s: %(message)s")
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)


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
        auth_key_pair = secretsmanager.get(get_env_var("LOKI_API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/loki/api/v1/query_range"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])
        session.params = {
                    'query': logql,
                    'limit': 5000
        }
        response = session.get(base_url)
        if response.headers['Content-Type'] == 'application/json':
                    response = response.json()
        else:
                    response = {"error": response.content}
        logger.info(response)
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
def get_available_loki_labels() -> Annotated[dict, Body(description="List of available Loki Labels from Grafana Cloud")]:
    # Adding custom logs
    logger.debug("get_available_labels - Invoked")
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="GetAvailableLabelsInvocations", unit=MetricUnit.Count, value=1)

    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("LOKI_API_SECRET_NAME"), transform='json')
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


@app.get("/invoke-promql", 
         summary="Invokes a given promql statement",
         description="Makes GET HTTP to Grafana Cloud to invoke a specified promql statement passed in the input .This calls \
         /api/v1/query endpoint from Grafana Prometheus host endpoint using basic authentication.\
         Secrets to call are stored in AWS Secrets Manager",
         operation_id="invokePromqlStatement",
         tags=["GrafanaCloud","Prometheus","Statement"],
         response_description="PromQL Statement invocation results from Grafana Cloud"
         )
@tracer.capture_method
def invoke_promql_statement(
    promql: Annotated[str, Query(description="The PromQL Statement to invoke", strict=True)]
) -> Annotated[dict, Body(description="Results from the promql statement")]:
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="PromQLInvocations", unit=MetricUnit.Count, value=1)   
    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("PROM_API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/api/v1/query"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])
        # Using this because directly accessing the promql input is truncating the records after comma
        # This does bypass the typing extension validation, but good enough to generate the openapi spec
        # without compromising 
        session.params = {'query': promql}
        logger.debug(session.params)
        response = session.get(base_url).json()
        return response
    except Exception as e:
        logger.error(str(e))
        raise 
    
@app.get("/get-available-promql-labels", 
         summary="Get available PromQL filter labels from Grafana Cloud",
         description="Makes GET HTTP to Grafana Cloud to get a list of available filter labels .This calls \
         api/v1/labels endpoint from Grafana Prometheus host endpoint using basic authentication.\
         Secrets to call are stored in AWS Secrets Manager",
         operation_id="getAvailablePrometheusLabels",
         tags=["GrafanaCloud","Prometheus","Labels"],
         response_description="List of available Prometheus labels from Grafana Cloud"
         )
@tracer.capture_method
def get_available_prometheus_labels() -> Annotated[list, Body(description="List of available Prometheus Labels from Grafana Cloud")]:
    # Adding custom logs
    logger.debug("get_available_labels - Invoked")
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="GetAvailableLabelsInvocations", unit=MetricUnit.Count, value=1)

    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("PROM_API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/api/v1/labels"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])   
        
        response = session.get(base_url).json()
        logger.debug("get_available_labels - HTTP 200")
        return response['data']
    except Exception as e:
        logger.error(str(e))
        raise 



@app.get("/get-available-metric-names", 
         summary="Get available prometheus metrics names from Grafana Cloud",
         description="Makes GET HTTP to Grafana Cloud to get a list of available Prometheus metric names.This calls \
         /api/v1/label/__name__/values endpoint from Grafana Prometheus host endpoint using basic authentication.\
         Secrets to call are stored in AWS Secrets Manager",
         operation_id="getAvailablePrometheusMetricNames",
         tags=["GrafanaCloud","Prometheus","Metrics"],
         response_description="List of available Prometheus metric namesfrom Grafana Cloud"
         )
@tracer.capture_method
def get_available_metric_names() -> Annotated[list, Body(description="List of available Prometheus metric names from Grafana Cloud")]:
    # Adding custom logs
    logger.debug("get-available-metric-names - Invoked")
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="GetAvailableMetricNamesInvocations", unit=MetricUnit.Count, value=1)

    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("PROM_API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/api/v1/label/__name__/values"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])   
        
        response = session.get(base_url).json()
        logger.debug("get_available_metrics - HTTP 200")
        return response['data']
    except Exception as e:
        logger.error(str(e))
        raise 