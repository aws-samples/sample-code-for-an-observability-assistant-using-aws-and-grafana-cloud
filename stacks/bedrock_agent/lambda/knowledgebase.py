from requests import request
import json
import os
import boto3
client = boto3.client('bedrock-agent')
# from crhelper import CfnResource
from time import sleep

import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def create(event):   
    logger.info("Got Create")
    sleep(15) 
    # This sleep is to ensure the datapolicy is added to the opensearch vector DB, otherwise the KB creation fails with
    # the reason of access denied
    try:
        response = client.create_knowledge_base(
               name='grafana-bedrock-kb-docs',
               description='This knowledge base can be used to understand how to generate a PromQL or LogQL.',
               roleArn=os.environ["BEDROCK_KB_ROLE_ARN"],
               knowledgeBaseConfiguration={
                   'type': 'VECTOR',
                   'vectorKnowledgeBaseConfiguration': {
                        'embeddingModelArn': f'arn:aws:bedrock:{os.environ["REGION"]}::foundation-model/amazon.titan-embed-text-v1'
                   }
               },
               storageConfiguration={
                   'type': 'OPENSEARCH_SERVERLESS',
                   'opensearchServerlessConfiguration': {
                       'collectionArn': os.environ["COLLECTION_ARN"],
                       'vectorIndexName': os.environ["INDEX_NAME"],
                       'fieldMapping': {
                           'metadataField': 'metadataField',
                           'textField': 'textField',
                           'vectorField': 'vectorField'
                       }
                   }
               }
        )

        logger.info(response)

        while True:
            kb_status = client.get_knowledge_base(knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId'])
            if kb_status['knowledgeBase']['status'] == 'ACTIVE':
                break
            sleep(5)

        obj_url_to_crawl = eval(os.environ["URLS_TO_CRAWL"])
        #Create a json object with every URL in the obj_url_to_crawl
        urls = [{"url": url} for url in obj_url_to_crawl]

        add_datasource_response = client.create_data_source(
            dataDeletionPolicy='DELETE',
            dataSourceConfiguration={
                'type': 'WEB',
                'webConfiguration': {
                    'crawlerConfiguration': {
                        'crawlerLimits': {
                            'rateLimit': 300
                        },
                    },
                    'sourceConfiguration': {
                        'urlConfiguration': {
                            'seedUrls': urls
                            # [
                            #     {
                            #         'url': 'https://promlabs.com/promql-cheat-sheet/'
                            #     },
                            #     {
                            #         'url': 'https://isitobservable.io/observability/prometheus/how-to-build-a-promql-prometheus-query-language'
                            #     },
                            #     {
                            #         'url': 'https://prometheus.io/docs/prometheus/latest/querying/'
                            #     },
                            #     {
                            #         'url': 'https://grafana.com/docs/loki/latest/query/'
                            #     },
                            #     {
                            #         'url': 'https://github.com/grafana/loki/tree/main/docs/sources/query'
                            #     }
                            # ]
                        }
                    }
                }
            },
            description='The Web data source for understanding how promql statements be constructed',
            knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId'],
            name='promql-datasource',
            vectorIngestionConfiguration={
                'chunkingConfiguration': {
                    'chunkingStrategy': 'FIXED_SIZE',
                    'fixedSizeChunkingConfiguration': {
                        'maxTokens': 300,
                        'overlapPercentage': 20
                    },
                }
            }
        )

        add_s3_datasource_response = client.create_data_source(
            dataDeletionPolicy='DELETE',
            dataSourceConfiguration={
                'type': 'S3',
                's3Configuration': {
                    'bucketArn': os.environ["KB_BUCKET"],
                    # 'bucketOwnerAccountId': 'string',
                    # 'inclusionPrefixes': [
                    #     'string',
                    # ]
                },
            },
            description='The S3 data source for understanding how logql statements be constructed',
            knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId'],
            name='s3-datasource',
            vectorIngestionConfiguration={
                'chunkingConfiguration': {
                    'chunkingStrategy': 'FIXED_SIZE',
                    'fixedSizeChunkingConfiguration': {
                        'maxTokens': 300,
                        'overlapPercentage': 20
                    },
                }
            }
        )

        # logger.info(add_datasource_response)

        
        
        while True:
            s3_datasource_status = client.get_data_source(knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId'],
                                                       dataSourceId=add_s3_datasource_response['dataSource']['dataSourceId'])
            if s3_datasource_status['dataSource']['status'] == 'AVAILABLE':
                break
            sleep(5)

        start_s3_ingestion_job_response = client.start_ingestion_job(
            dataSourceId=add_s3_datasource_response['dataSource']['dataSourceId'],
            knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId']
        )

        while True:
            s3_ingestion_job_status = client.get_ingestion_job(
                knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId'],
                dataSourceId=add_s3_datasource_response['dataSource']['dataSourceId'],
                ingestionJobId=start_s3_ingestion_job_response['ingestionJob']['ingestionJobId']
            )
            if s3_ingestion_job_status['ingestionJob']['status'] == 'COMPLETE':
                break
            sleep(5)
        
        while True:
            datasource_status = client.get_data_source(knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId'],
                                                       dataSourceId=add_datasource_response['dataSource']['dataSourceId'])
            if datasource_status['dataSource']['status'] == 'AVAILABLE':
                break
            sleep(5)

        start_ingestion_job_response = client.start_ingestion_job(
            dataSourceId=add_datasource_response['dataSource']['dataSourceId'],
            knowledgeBaseId=response['knowledgeBase']['knowledgeBaseId']
        )

        logger.info(start_ingestion_job_response)
        logger.info(start_s3_ingestion_job_response)
        return {'PhysicalResourceId': response['knowledgeBase']['knowledgeBaseId']}
    except Exception as e:
        print(e)


def delete(event):   
    logger.info("Got Delete")
    try:
        client.delete_knowledge_base(knowledgeBaseId=event["PhysicalResourceId"])
    except Exception as e:
        print(e)

def handler(event, context):
    logger.info(event)
    print(event)
    request_type = event['RequestType'].lower()
    if request_type == 'create':
        return create(event)
    if request_type == 'delete':
        return delete(event)
    raise Exception(f'Invalid request type: {request_type}')