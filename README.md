
# Sample code for an Observability Assistant for Grafana Cloud using AWS Bedrock Agents

## Pre Deployment Actions
### Create Self Signed Certificate and Upload to ACM

* Private Key - `openssl genrsa -out ca-key.pem 2048`
* Cert - `openssl req -new -x509 -nodes -days 365    -key ca-key.pem    -out ca-cert.pem`
* Upload to ACM - `aws acm import-certificate --certificate fileb://ca-cert.pem --private-key fileb://ca-key.pem`
* Note the ARN and mention that under `config/development.yaml` file

### Adding Secrets to Secrets Manager, one each for `Loki` and `Prometheus`. The secrets MUST be in the following format

```
{
"baseUrl" : "FILL ME WITH THE BASE URL FOR YOUR LOKI OR PROMETHEUS",
"username":"FILL ME WITH THE USERNAME FOR LOKI OR PROMETHEUS",
"apikey":"FILL IN WITH THE API KEY FOR LOKI OR PROMETHEUS"
}
```

Note the secret names from secrets manager under `config/development` at the `LogsSecretName` for Loki and `MetricsSecretName` for Prometheus

## Deploy Commands

* Bootstrap CDK Environment - `cdk boostrap`
* Change the mutability of the ECR registry created. If you dont do this then docker push command may fail
* CDK Synth - `cdk synth --context environment=development`
* CDK Deploy - `cdk deploy --context environment=development --all`
* CDK Deploy (no prompt) - `cdk deploy --context environment=development --all --require-approval never`

Deployment will create the following implementation

![image](./images/grafana-genai-asssistant.jpeg)

## Post Deployment actions

* Create a user to login in the Cognito Pool