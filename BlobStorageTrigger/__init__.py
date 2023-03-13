import logging
import azure.functions as func
import logging
from azure.storage.blob import BlobServiceClient
import os
from azure.cosmos import CosmosClient

def main(myblob: func.InputStream):
    blob_connection_string = os.environ.get("TAG_BLOB_CONNECTION_STRING", None)
    url = os.environ.get("TAG_COSMOS_URL", None)
    key = os.environ.get("TAG_COSMOS_KEY", None)
    databaseName = os.environ.get("TAG_COSMOS_DATABASE_NAME", None)
    containerName = os.environ.get("TAG_COSMOS_CONTAINER_NAME", None)

    blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)

    container_client = blob_service_client.get_container_client("tagdata")

    blob_client = container_client.get_blob_client(myblob.name.split('/')[1])

    data = blob_client.download_blob()

    strContent = data.content_as_text(encoding="utf-8-sig").split("\r\n")

    cosmosClient = CosmosClient(url, key)

    database = cosmosClient.get_database_client(databaseName)
    container = database.get_container_client(containerName)

    for item in strContent:
        if len(item) > 0:
            columns = item.split(",")
            container.upsert_item({"id": columns[0], "appName": columns[1], "owner": columns[2], "ctime": columns[3] })

    logging.info('Python Blob trigger function processed %s', myblob.name)