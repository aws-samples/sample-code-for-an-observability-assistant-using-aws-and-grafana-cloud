import boto3
import json
import os
from botocore.exceptions import ClientError
output_text = ""
citations = []
trace = {}
import requests
requests.packages.urllib3.add_stderr_logger() 

knowledge_base_id = os.environ.get("KNOWLEDGEBASE_ID")
function_calling_url = os.environ.get("FUNCTION_CALLING_URL")

def invoke_agent_ROC(agent_id, agent_alias_id, session_id,invocation_id,return_control_invocation_results):
    print(return_control_invocation_results)
    print(type(return_control_invocation_results))
    client = boto3.session.Session().client(service_name="bedrock-agent-runtime")
    response = client.invoke_agent(
            agentId=agent_id,
            agentAliasId=agent_alias_id,
            enableTrace=True,
            sessionId=session_id,
            sessionState = {
                'invocationId': invocation_id,
                'returnControlInvocationResults': return_control_invocation_results,
                'knowledgeBaseConfigurations': [
                    {
                        'knowledgeBaseId': knowledge_base_id, # Replace with your knowledge base ID
                        'retrievalConfiguration': {
                            'vectorSearchConfiguration':{
                                'overrideSearchType': 'HYBRID',
                                'numberOfResults': 100
                            }
                            
                        }
                    }
                ]
            }
        )
    process_response(response,agent_id, agent_alias_id, session_id)
    
def invoke_agent(agent_id, agent_alias_id, session_id, prompt):
    try:
        client = boto3.session.Session().client(service_name="bedrock-agent-runtime")
        # See https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-agent-runtime/client/invoke_agent.html
        response = client.invoke_agent(
            agentId=agent_id,
            agentAliasId=agent_alias_id,
            enableTrace=True,
            sessionId=session_id,
            inputText=prompt,
            sessionState = {
             'knowledgeBaseConfigurations': [
                {
                    'knowledgeBaseId': knowledge_base_id, # Replace with your knowledge base ID
                    'retrievalConfiguration': {
                         'vectorSearchConfiguration':{
                            'overrideSearchType': 'HYBRID',
                            'numberOfResults': 100
                         }
                         
                    }
                }
            ]
            }
        )
        global output_text, citations, trace
        output_text = ""
        citations = []
        trace = {}
        process_response(response,agent_id, agent_alias_id, session_id)
    except ClientError as e:
        raise

    return {
        "output_text": output_text,
        "citations": citations,
        "trace": trace
    }


def process_response(response,agent_id, agent_alias_id, session_id):
    
    global output_text, citations, trace
    
    for event in response.get("completion"):

            #Implementing Return of Control to call the code locally

            if 'returnControl' in event:
                # return_control_invocation_results = []
                return_control = event['returnControl']
                invocation_id = return_control['invocationId']
                invocation_inputs = return_control['invocationInputs']

                for invocation_input in invocation_inputs:
                    function_invocation_input = invocation_input['apiInvocationInput']
                    api_response = get_data_from_api(function_invocation_input)
                    # return_control_invocation_results.append( 
                    #     {
                    #         'apiResult': lambda_response['response']
                    #     }
                    # )
                    invoke_agent_ROC(agent_id, agent_alias_id, session_id, invocation_id,api_response)
                        
            # Combine the chunks to get the output text
            elif "chunk" in event:
                chunk = event["chunk"]
                output_text += chunk["bytes"].decode()
                if "attribution" in chunk:
                    citations = citations + chunk["attribution"]["citations"]

            # Extract trace information from all events
            elif "trace" in event:
                for trace_type in ["preProcessingTrace", "orchestrationTrace", "postProcessingTrace","actionGroupInvocationOutput","knowledgeBaseLookupOutput"]:
                    if trace_type in event["trace"]["trace"]:
                        if trace_type not in trace:
                            trace[trace_type] = []
                        trace[trace_type].append(event["trace"]["trace"][trace_type])

# Function which calls the local lambda function to get the data
def get_data_from_api(parameters):
    return_function_response = parameters
    path_to_invoke = "http://"+function_calling_url+return_function_response['apiPath'] #TODO: Pass the protocol from ALB
    # method_to_invoke = return_function_response['httpMethod']
    parameters_to_pass = return_function_response['parameters']
    # Check if the parameters_to_pass is not None

    if not len(parameters_to_pass) == 0:
        parameters_to_pass = parameters_to_pass[0]['value']
    # {'actionGroup': 'logs-api-caller', 'actionInvocationType': 'RESULT', 'apiPath': '/get-available-logql-labels', 'httpMethod': 'GET', 'parameters': []}
    session = requests.Session()
    session.params = {
            'logql': parameters_to_pass
    }
    
    response = session.get(path_to_invoke).json()
    print("=====RESPONSE FROM API=======")
    print(response)
    print("=====RESPONSE FROM API ENDS=======")
    response_body = {"application/json": {"body": json.dumps(response)}}
    api_response = [{
                'apiResult': {
                    'actionGroup': return_function_response['actionGroup'],
                    'apiPath': return_function_response['apiPath'],
                    # 'confirmationState': 'CONFIRM'|'DENY',
                    'httpMethod': return_function_response['httpMethod'],
                    # 'httpStatusCode': response.status_code,
                    'responseBody': response_body,
                    # 'responseState': 'FAILURE'|'REPROMPT'
                }
    }]

    return api_response