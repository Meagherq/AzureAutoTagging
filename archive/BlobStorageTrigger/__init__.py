import logging
import azure.functions as func
import logging
from azure.storage.blob import BlobServiceClient
import os
from azure.cosmos import CosmosClient
import smtplib
from smtplib import SMTPException
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

import base64
import sys
import uuid

from azure.identity import ClientSecretCredential

from azure.keyvault.keys.crypto import CryptographyClient, KeyWrapAlgorithm
from azure.keyvault.keys import KeyVaultKey, KeyType
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential

from azure.storage.blob import BlobServiceClient

def main(myblob: func.InputStream):

    # Blob Storage SDK Appsettings 
    blob_connection_string = os.environ.get("BLOB_CONNECTION_STRING", None)
    blob_container_name = os.environ.get("BLOB_CONTAINER_NAME", None)
    keyvault_url = os.environ.get("KEYVAULT_URL")
    clientId = os.environ.get("CLIENT_ID", None)
    clientSecret = os.environ.get("CLIENT_SECRET", None)
    tenantId = os.environ.get("TENANT_ID", None)

    # CosmosDB SDK Appsettings
    url = os.environ.get("COSMOS_URL", None)
    key = os.environ.get("COSMOS_KEY", None)
    databaseName = os.environ.get("COSMOS_DATABASE_NAME", None)
    containerName = os.environ.get("COSMOS_CONTAINER_NAME", None)

    #credential = ClientSecretCredential(tenantId, clientId, clientSecret)
    credential = DefaultAzureCredential()
    secret_client = SecretClient(keyvault_url, credential=credential)

    secret = secret_client.get_secret('auto-tag-func-cmk')
    key_bytes = base64.urlsafe_b64decode(secret.value)
    kvk = KeyVaultKey(key_id=secret.id, key_ops=['unwrapKey', 'wrapKey'], k=key_bytes, kty=KeyType.oct)
    kek = KeyWrapper(kvk, credential)

    # Instatinate Blob Storage client using connection string
    blob_service_client = BlobServiceClient.from_connection_string(blob_connection_string, credential=credential)

    # Instantiate Blob Storage Container Client using Blob Storage Client
    container_client = blob_service_client.get_container_client(blob_container_name)
    container_client.key_encryption_key = kek
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

    try:
    # Iterate through each entry and upsert to CosmosDB
        for item in strContent:
            # Filter out lines that don't have any content
            if len(item) > 0:
                # Split each row into the set of columns
                columns = item.split(",")
                # Perform to upsert to CosmosDB using the CosmosDB Container Client
                container.upsert_item({"id": columns[0], "appName": columns[1], "owner": columns[2] })
    except:
        sendmail(myblob.name.split('/')[1])
        print("mail sent unsuccessful")

    sendmail(myblob.name.split('/')[1])
    logging.info('Python Blob trigger function processed %s', myblob.name)

def sendmail(blobName):

    # Email Appsettings
    sender_email_address = os.environ.get("SENDER_EMAIL_ADDRESS", None)
    # sender_email_password = os.environ.get("SENDER_EMAIL_PASSWORD", None)
    receipient_email_address = os.environ.get("RECEIPIENT_EMAIL_ADDRESS", None)
    smtp_server = os.environ.get("SMTP_SERVER", None)
    smtp_port = os.environ.get("SMTP_PORT", None)
    
    msg = MIMEMultipart()
    msg['From'] = sender_email_address
    msg['To'] = receipient_email_address
    msg['Subject'] = 'Unsuccessful CosmosDB CSV Update'
    message = 'CSV tag data update was unsuccessful for Filename: ' + blobName
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

class KeyWrapper:
    """ Class that fulfills the interface used by the storage SDK's
        automatic client-side encyrption and decryption routines. """

    def __init__(self, kek, credential):
        self.algorithm = KeyWrapAlgorithm.aes_256
        self.kek = kek
        self.kid = kek.id
        self.client = CryptographyClient(kek, credential)

    def wrap_key(self, key):
        if self.algorithm != KeyWrapAlgorithm.aes_256:
            raise ValueError('Unknown key wrap algorithm. {}'.format(self.algorithm))
        wrapped = self.client.wrap_key(key=key, algorithm=self.algorithm)
        return wrapped.encrypted_key

    def unwrap_key(self, key, _):
        if self.algorithm != KeyWrapAlgorithm.aes_256:
            raise ValueError('Unknown key wrap algorithm. {}'.format(self.algorithm))
        unwrapped = self.client.unwrap_key(encrypted_key=key, algorithm=self.algorithm)
        return unwrapped.key

    def get_key_wrap_algorithm(self):
        return self.algorithm

    def get_kid(self):
        return self.kid