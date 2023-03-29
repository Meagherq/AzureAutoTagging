import json
import os

from azure.identity import ClientSecretCredential
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.v2022_09_01.models import TagsResource
from azure.cosmos import CosmosClient
import azure.functions as func
from string import Template

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
    clientId = os.environ.get("TAG_CLIENT_ID", None)
    clientSecret = os.environ.get("TAG_CLIENT_SECRET", None)
    tenantId = os.environ.get("TAG_TENANT_ID", None)
    authority = os.environ.get("TAG_AUTHORITY", None)
    subscriptionId = os.environ.get("TAG_SUBSCRIPTION_ID", None)

    # CosmosDB SDK Appsettings
    url = os.environ.get("TAG_COSMOS_URL", None)
    key = os.environ.get("TAG_COSMOS_KEY", None)
    databaseName = os.environ.get("TAG_COSMOS_DATABASE_NAME", None)
    containerName = os.environ.get("TAG_COSMOS_CONTAINER_NAME", None)

    # Instantiate Resource Management Client to query and update tags
    resource_client = ResourceManagementClient(
        credential=ClientSecretCredential(tenantId, clientId, clientSecret, authority=authority),
        subscription_id=subscriptionId,
        api_version="2020-10-01"
    )

    # Instantiate empty tag
    existingData = TagsResource
    appIdTag = any

    # Instantiate CosmosDB Client using the url and access key
    cosmosClient = CosmosClient(url, key)

    # Intantiate CosmosDB Database Client using CosmosDB Client
    database = cosmosClient.get_database_client(databaseName)

    # Instantiate CosmosDB Container Client using CosmosDB Database Client
    container = database.get_container_client(containerName)

    # Instantiate empty dictionary to hold queried tagData
    cosmosTagData = dict[str, any]

    # Create query template where $n1 is the existing AppId tag value
    queryTemplate = Template('SELECT * FROM c where c.id = "$n1"')

    # Query for existing tags
    try:
        # Filter out invalid operations
        if 'operationName' in data:
            # if 'Microsoft.Resources/tags/write' in data['operationName'] or 'Microsoft.Resources/deployments/write' in data['operationName']:
            if 'Microsoft.Resources/tags/write' in data['operationName']:
                print("Operation was filtered for Uri: " + data['resourceUri'] + " | " + data['operationName'])
                return func.HttpResponse("Ignore tag write operation", status_code=400)
            
            # Check if the operation is a deployment rather then a direct resource provider operation
            # E.g OperationName of 'Microsoft.Resources/deployments/write' instead of 'Microsoft.StorageAccounts/write'
            if 'Microsoft.Resources/deployments/write' in data['operationName']:

                # Query for deployment information which contains the list of output resources
                existingDeployment = resource_client.resources.get_by_id(data['resourceUri'], '2021-04-01')

                # Check if the deployment has outputResources
                if 'outputResources' in existingDeployment.properties:
                    outputResources = existingDeployment.properties.get('outputResources')

                    # Iterate through output resources, applying tags to any valid resources
                    for resource in outputResources:
                        existingDataForResource = TagsResource
                        appIdTagForResource = any
                        cosmosTagDataForResource = dict[str, any]
                        try:
                            # Get existing tags for resource from deployment output resource
                            existingDataForResource = resource_client.tags.get_at_scope(resource['id'])

                            # Check is AppId tag exists
                            if 'appId' in existingDataForResource.properties.tags:
                                appIdTagForResource = existingDataForResource.properties.tags["appId"]

                            # Check if we have already applied complex tags
                            if 'appName' in existingDataForResource.properties.tags or 'owner' in existingDataForResource.properties.tags:
                                print("Tag updates are already in place for deployed resources")
                                return func.HttpResponse("Tag updates are already in place for deployed resources", status_code=400)  

                            # Query for complex tags from CosmosDB using the existing AppId tag
                            for item in container.query_items(
                                query=queryTemplate.substitute(n1 = appIdTagForResource),
                                enable_cross_partition_query=True,
                            ):
                                # Copy query response into cosmosTagDataForResource dictionary
                                cosmosTagDataForResource = item.copy()

                            # Create the resource tags for the given resourceUri using the queried tags from CosmosDB
                            resource_client.tags.create_or_update_at_scope(resource['id'], { "operation": "create", "properties": {
                            "tags": { "appId": appIdTagForResource, "appName": cosmosTagDataForResource.get('appName'), "owner": cosmosTagDataForResource.get('owner'), "ctime": cosmosTagDataForResource.get('ctime') }}})
                        except:
                            print("Deployment resource does not support tags or tags were not successfully added")

                    # Proper status code response prevent excessive retry
                    return func.HttpResponse("Tag updates were processed for deployment resources", status_code=200)
   
            else:
                # Get tags using resourceUri scope
                existingData = resource_client.tags.get_at_scope(
                data['resourceUri'])
                appIdTag = existingData.properties.tags["appId"]

                if 'appName' in existingData.properties.tags or 'owner' in existingData.properties.tags:
                    print("Tag updates are already in place for resources")
                    # Proper status code response prevent excessive retry
                    return func.HttpResponse("Tag updates are already in place for resource", status_code=400)  
    except:
        print("Resource does not support tags: " + data['resourceUri'])

        # If the request does not have an appId tag or does not support tags the function returns.
        return func.HttpResponse("Resource does not support tags or does not contain AppId tag", status_code=400)

    # Query for complex tags from CosmosDB using the existing AppId tag
    for item in container.query_items(
        query=queryTemplate.substitute(n1 = appIdTag),
        enable_cross_partition_query=True,
    ):
        # Copy query response into cosmosTagData dictionary
        cosmosTagData = item.copy()

    try:
        # Create the resource tags for the given resourceUri using the queried tags from CosmosDB
        resource_client.tags.create_or_update_at_scope(data['resourceUri'], { "operation": "create", "properties": {
        "tags": { "appId": appIdTag, "appName": cosmosTagData.get('appName'), "owner": cosmosTagData.get('owner'), "ctime": cosmosTagData.get('ctime') }
        }})
    except:
        print("Tag updates were unsuccessful for: " + data['resourceUri'])
        # Proper status code response prevent excessive retry
        return func.HttpResponse("Tag updates were unsuccessful for: " + data['resourceUri'], status_code=400)

    print("Tag updates were successful for: " + data['resourceUri'])
    # Proper status code response prevent excessive retry
    return func.HttpResponse("Tag updates were successful for: " + data['resourceUri'], status_code=200)