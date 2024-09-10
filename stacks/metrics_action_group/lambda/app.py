import os
from aws_lambda_powertools.event_handler import BedrockAgentResolver
from aws_lambda_powertools.utilities.typing import LambdaContext
# from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools import Logger
from aws_lambda_powertools import Tracer
from aws_lambda_powertools import Metrics
from aws_lambda_powertools.metrics import MetricUnit
import requests
from requests.exceptions import HTTPError
from aws_lambda_powertools.utilities import parameters
from typing_extensions import Annotated
from aws_lambda_powertools.event_handler.openapi.params import Body, Query

app = BedrockAgentResolver(enable_validation=True)
tracer = Tracer()
logger = Logger()
metrics = Metrics(namespace="MetricsLambdaAgent")
secretsmanager = parameters.SecretsProvider()

#Enable this only when required to enable HTTP trace
# requests.packages.urllib3.add_stderr_logger() 

# Methond gets the environment variables from OS
def get_env_var(var_name):
    try:
        return os.environ[var_name]
    except KeyError:
        logger.error(f"Environment variable {var_name} is not set.")
        return None
    
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
        auth_key_pair = secretsmanager.get(get_env_var("API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/api/v1/query"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])
        # Using this because directly accessing the promql input is truncating the records after comma
        # This does bypass the typing extension validation, but good enough to generate the openapi spec
        # without compromising 
        session.params = {'query': app.current_event.parameters[0]['value']}
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
def get_available_labels() -> Annotated[list, Body(description="List of available Prometheus Labels from Grafana Cloud")]:
    # Adding custom logs
    logger.debug("get_available_labels - Invoked")
    # adding custom metrics
    # See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/metrics/
    metrics.add_metric(name="GetAvailableLabelsInvocations", unit=MetricUnit.Count, value=1)

    # Try Except block to make Grafana Cloud API call
    try:
        auth_key_pair = secretsmanager.get(get_env_var("API_SECRET_NAME"), transform='json')
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
        auth_key_pair = secretsmanager.get(get_env_var("API_SECRET_NAME"), transform='json')
        base_url = auth_key_pair['baseUrl']+"/api/v1/label/__name__/values"
        session = requests.Session()
        session.auth = (auth_key_pair['username'], auth_key_pair['apikey'])   
        
        response = session.get(base_url).json()
        logger.debug("get_available_metrics - HTTP 200")
        return response['data']
    except Exception as e:
        logger.error(str(e))
        raise 

# Enrich logging with contextual information from Lambda
# @logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
# Adding tracer
# See: https://awslabs.github.io/aws-lambda-powertools-python/latest/core/tracer/
@logger.inject_lambda_context
@tracer.capture_lambda_handler
# ensures metrics are flushed upon request completion/failure and capturing ColdStart metric
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event: dict, context: LambdaContext) -> dict:
    logger.info(event)
    return app.resolve(event, context)

if __name__ == "__main__":  
    print(app.get_openapi_json_schema(openapi_version='3.0.0')) 