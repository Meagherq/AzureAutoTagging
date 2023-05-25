import json
import os
import logging
from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.v2022_09_01.models import TagsResource
from azure.cosmos import CosmosClient
import azure.functions as func
from string import Template
import datetime
import smtplib
from smtplib import SMTPException
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication


# EventGrid can use an HttpTrigger or a classic EventGridTrigger
# If you want to use a EventGridTrigger
# def main(event: func.EventGridEvent):

#     result = json.dumps({
#         'id': event.id,
#         'data': event.get_json(),
#         'topic': event.topic,
#         'subject': event.subject,
#         'event_type': event.event_type,
#     })

def main(req: func.HttpRequest) -> func.HttpResponse:

    # Turn response body into Python object
    req_body = req.get_json()

    # Grab the first object in the response body
    body = req_body[0]

    # The data property holds the main payload. For validation, this contains the validation code
    data = body['data']

    # Validation Process: Creation of EventGrid subscription will send a validationCode.
    # Subscription is validated when the validationCode is returned with a 200 status code response.
    if 'validationCode' in data:
        return func.HttpResponse(json.dumps({"validationResponse": data['validationCode']}), status_code=200)

    # Resource Management SDK Appsettings
    clientId = os.environ.get("CLIENT_ID", None)
    clientSecret = os.environ.get("CLIENT_SECRET", None)
    tenantId = os.environ.get("TENANT_ID", None)
    authority = os.environ.get("AUTHORITY", None)
    subscriptionId = os.environ.get("SUBSCRIPTION_ID", None)

    # CosmosDB SDK Appsettings
    url = os.environ.get("COSMOS_URL", None)
    key = os.environ.get("COSMOS_KEY", None)
    databaseName = os.environ.get("COSMOS_DATABASE_NAME", None)
    containerName = os.environ.get("COSMOS_CONTAINER_NAME", None)

    # Instantiate Resource Management Client to query and update tags
    resource_client = ResourceManagementClient(
        credential=ClientSecretCredential(tenantId, clientId, clientSecret, authority=authority),
        subscription_id=subscriptionId,
        api_version="2020-10-01"
    )

    # Instantiate CosmosDB Client using the url and access key
    cosmosClient = CosmosClient(url, key)

    # Intantiate CosmosDB Database Client using CosmosDB Client
    database = cosmosClient.get_database_client(databaseName)

    # Instantiate CosmosDB Container Client using CosmosDB Database Client
    container = database.get_container_client(containerName)

    if 'operationName' in data:
            # if 'Microsoft.Resources/tags/write' in data['operationName'] or 'Microsoft.Resources/deployments/write' in data['operationName']:
            if 'Microsoft.Resources/tags/write' in data['operationName']:
                logging.info("Operation was filtered for Uri: " + data['resourceUri'] + " | " + data['operationName'])
                return func.HttpResponse("Operation was filtered for Uri: " + data['resourceUri'] + " | " + data['operationName'], status_code=400)

            # Update tags for a group of deployments such as a multi-resource ARM template
            if 'Microsoft.Resources/deployments/write' in data['operationName']:
                # Query for deployment information which contains the list of output resources
                existingDeployment = resource_client.resources.get_by_id(data['resourceUri'], '2021-04-01')

                # Check if the deployment has outputResources. 
                # outputResources contains the list of resources successfully created via group deployment.
                if 'outputResources' in existingDeployment.properties:
                    outputResources = existingDeployment.properties.get('outputResources')
                
                # Create empty error context in case of failed tag operations.
                # This allows us to log any errors while continuing to tag additional resources.
                errorDict = dict[str, any]
                # Iterate through outputResources, applying tags to any valid resources
                for resource in outputResources:
                    try:
                        updateTags(resource['id'], container, resource_client)
                    except Exception as e:
                        # Update error context with unsuccessful tag update information
                        errorDict[resource['id']] = e.message

                # Check if error context is has entries.
                if errorDict:
                    response = {
                        "Description": "Some tag updates were unsuccessful for group deployment: " + data['resourceUri'],
                        "Context": json.dumps(errorDict)
                    }
                    logging.info(json.dumps(response))
                    return func.HttpResponse(json.dumps(response), status_code=200)
                
                # Else if all updates were successful. Error context is empty here.
                else:
                    logging.info("All tag updates were successful for group deployment: " + data['resourceUri'])
                    return func.HttpResponse("All tag updates were successful for group deployment: " + data['resourceUri'], status_code=200)

            # Update tags for a resource creation using a Service Provider such as 'Microsoft.StorageAccounts/write'
            else: 
                try:
                    updateTags(data['resourceUri'], container, resource_client)
                    logging.info("Tag updates were successful for: " + data['resourceUri'])
                    return func.HttpResponse("Tag updates were successful for: " + data['resourceUri'], status_code=200)
                except Exception as e:
                        # Use error raised from updateTags to log and return the error
                        logging.error("Error updating tags for " + data['resourceUri'] + " : " + json.dumps(e))
                        return func.HttpResponse("Error updating tags for " + data['resourceUri'] + " : " + json.dumps(e), status_code=400)

def updateTags(resourceUri: str, cosmosClient: any, resourceClient: ResourceManagementClient):
    existingTags: TagsResource

    try: 
        existingTags = resourceClient.tags.get_at_scope(resourceUri)
    except: 
        raise Exception("Tags are not support for: " + resourceUri)
    
    try:
        creationDate = resourceClient.resources.get_by_id(resourceUri, '2023-02-01').additional_properties['systemData']['createdAt']
    except:
        creationDate = "N/A"

    existingTagsWithInvariantCase: dict[str, str]
    try:
        # Create cloned dictionary with uppercase keys for comparison
        existingTagsWithInvariantCase = {k.upper():v for k,v in existingTags.properties.tags.items()}
    except:
        raise Exception("Could not compare tags for: " + resourceUri)

    if 'APPID' not in existingTagsWithInvariantCase:
        raise Exception("Valid AppId tag not found for: " + resourceUri)

    appIdTagValue = existingTagsWithInvariantCase['APPID']

    # Instantiate empty dictionary to hold queried tagData
    cosmosTagData = dict[str, any]
    # Create query template where $n1 is the existing AppId tag value
    queryTemplate = Template('SELECT * FROM c where c.id = "$n1"')

    try:
        # Query for complex tags from CosmosDB using the existing AppId tag
        for item in cosmosClient.query_items(
        query=queryTemplate.substitute(n1 = appIdTagValue),
        enable_cross_partition_query=True,
        ):
            
        # Copy query response into cosmosTagData dictionary
            cosmosTagData = item.copy()

    except Exception as e:
        raise Exception("Cosmos could not query for AppId:" + appIdTagValue + " - " + e.message)
    
    # Apply complex tags from CosmosDB
    try:
        existingTags.properties.tags["Appname"] = cosmosTagData.get('appName')
        existingTags.properties.tags["Owner"] = cosmosTagData.get('owner')
        existingTags.properties.tags["bax-ctime"] = creationDate

        # Update tags at scope
        resourceClient.tags.create_or_update_at_scope(resourceUri, { "operation": "create", "properties": {
          "tags": existingTags.properties.tags
        }})
    except Exception as e:
        raise Exception("Tag update error for resourceUri:" + resourceUri + " - " + e.message)

    
def sendmail(resourceUri):

    # Email Appsettings
    sender_email_address = os.environ.get("SENDER_EMAIL_ADDRESS", None)
    # sender_email_password = os.environ.get("SENDER_EMAIL_PASSWORD", None)
    receipient_email_address = os.environ.get("RECEIPIENT_EMAIL_ADDRESS", None)
    smtp_server = os.environ.get("SMTP_SERVER", None)
    smtp_port = os.environ.get("SMTP_PORT", None)

    msg = MIMEMultipart()
    msg['From'] = sender_email_address
    msg['To'] = receipient_email_address
    msg['Subject'] = 'Unsuccessful Tag Update Operation'
    message = 'Tag update was unsuccessful for ResourceId: ' + resourceUri
    msg.attach(MIMEText(message))
    mailserver = smtplib.SMTP(smtp_server, smtp_port)
    # identify ourselves to smtp client
    mailserver.ehlo()
    # secure our email with tls encryption
    mailserver.starttls()
    # re-identify ourselves as an encrypted connection
    mailserver.ehlo()
    # mailserver.login(sender_email_address, sender_email_password)
    mailserver.sendmail(msg['From'], msg['To'], msg.as_string())
    mailserver.quit()
