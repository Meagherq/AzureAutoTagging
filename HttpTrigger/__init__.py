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
    req_body = req.get_json()

    body = req_body[0]

    data = body['data']

    validationCode = any

    try:
        validationCode = data['validationCode']
        return func.HttpResponse(json.dumps({"validationResponse": validationCode}))
    except:
        print("Error")

    clientId = os.environ.get("TAG_CLIENT_ID", None)
    clientSecret = os.environ.get("TAG_CLIENT_SECRET", None)
    tenantId = os.environ.get("TAG_TENANT_ID", None)
    authority = os.environ.get("TAG_AUTHORITY", None)
    subscriptionId = os.environ.get("TAG_SUBSCRIPTION_ID", None)
    url = os.environ.get("TAG_COSMOS_URL", None)
    key = os.environ.get("TAG_COSMOS_KEY", None)
    databaseName = os.environ.get("TAG_COSMOS_DATABASE_NAME", None)
    containerName = os.environ.get("TAG_COSMOS_CONTAINER_NAME", None)

    resource_client = ResourceManagementClient(
        credential=ClientSecretCredential(tenantId, clientId, clientSecret, authority=authority),
        subscription_id=subscriptionId,
        api_version="2020-10-01"
    )

    existingData = TagsResource
    appIdTag = any

    try:
        if 'operationName' in data:
            if 'Microsoft.Resources/tags/write' in data['operationName']:
                return func.HttpResponse("Ignore tag write operation")

        existingData = resource_client.tags.get_at_scope(
        data['resourceUri'])
        appIdTag = existingData.properties.tags["appId"]
    except:
        print("Resource does not support tags")
        return func.HttpResponse("Resource does not support tags or does not contain AppId tag")

    cosmosClient = CosmosClient(url, key)

    database = cosmosClient.get_database_client(databaseName)
    container = database.get_container_client(containerName)

    cosmosTagData = dict[str, any]

    queryTemplate = Template('SELECT * FROM c where c.id = "$n1"')

    for item in container.query_items(
        query=queryTemplate.substitute(n1 = appIdTag),
        enable_cross_partition_query=True,
    ):
        cosmosTagData = item.copy()

    resource_client.tags.create_or_update_at_scope(data['resourceUri'], { "operation": "create", "properties": {
        "tags": { "appId": appIdTag, "appName": cosmosTagData.get('appName'), "owner": cosmosTagData.get('owner'), "ctime": cosmosTagData.get('ctime') }
    }})

    return func.HttpResponse(f"Hello. This HTTP triggered function executed successfully.")