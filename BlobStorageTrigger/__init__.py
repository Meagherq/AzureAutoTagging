import logging
import azure.functions as func
import logging
from azure.storage.blob import BlobServiceClient
import os
from azure.cosmos import CosmosClient
import datetime

def main(myblob: func.InputStream):

    # Blob Storage SDK Appsettings 
    blob_connection_string = os.environ.get("TAG_BLOB_CONNECTION_STRING", None)
    blob_container_name = os.environ.get("TAG_COSMOS_URL", None)

    # CosmosDB SDK Appsettings
    url = os.environ.get("TAG_COSMOS_URL", None)
    key = os.environ.get("TAG_COSMOS_KEY", None)
    databaseName = os.environ.get("TAG_COSMOS_DATABASE_NAME", None)
    containerName = os.environ.get("TAG_COSMOS_CONTAINER_NAME", None)

    # Instatinate Blob Storage client using connection string
    blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string)

    # Instantiate Blob Storage Container Client using Blob Storage Client
    container_client = blob_service_client.get_container_client(blob_container_name)

    # Instantiate Blob Storage Blob Client using Blob Storage Container Client
    blob_client = container_client.get_blob_client(myblob.name.split('/')[1])

    # Download Blob as byte content 
    data = blob_client.download_blob()

    # Format byte content as string without encoded character. Content is split into an array by line 
    strContent = data.content_as_text(encoding="utf-8-sig").split("\r\n")

    # Remove first element to account for headers
    strContent = strContent[1:]

    # Instantiate CosmosDB Client using the url and access key
    cosmosClient = CosmosClient(url, key)

    # Intantiate CosmosDB Database Client using CosmosDB Client
    database = cosmosClient.get_database_client(databaseName)
    
    # Instantiate CosmosDB Container Client using CosmosDB Database Client
    container = database.get_container_client(containerName)

    # Iterate through each entry and upsert to CosmosDB
    for item in strContent:
        # Filter out lines that don't have any content
        if len(item) > 0:
            # Split each row into the set of columns
            columns = item.split(",")
            # Perform to upsert to CosmosDB using the CosmosDB Container Client
            container.upsert_item({"id": columns[0], "appName": columns[1], "owner": columns[2], "ctime": datetime.datetime.now().ctime() })

    logging.info('Python Blob trigger function processed %s', myblob.name)