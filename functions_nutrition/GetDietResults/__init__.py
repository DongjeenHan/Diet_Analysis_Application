import json
import os
import azure.functions as func
from azure.storage.blob import BlobServiceClient

# Blob settings (must match your Blob Trigger output)
CONTAINER_NAME = os.environ.get("DATASET_CONTAINER", "datasets")
SUMMARY_BLOB_NAME = os.environ.get("SUMMARY_BLOB", "summaries.json")

# Local fallback for development
LOCAL_PATH = os.environ.get("SIMULATED_NOSQL_PATH", "simulated_nosql/results.json")

DEFAULT_CONN = os.environ.get(
    "AZURE_STORAGE_CONNECTION_STRING",
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)

def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    HTTP API that returns PRECOMPUTED results only.
    NO recalculation happens here.
    """


    try:
        blob_service = BlobServiceClient.from_connection_string(DEFAULT_CONN)
        container_client = blob_service.get_container_client(CONTAINER_NAME)
        blob_client = container_client.get_blob_client(SUMMARY_BLOB_NAME)

        data_bytes = blob_client.download_blob().readall()
        data = json.loads(data_bytes.decode("utf-8"))

        source = "blob"

    except Exception:
        try:
            with open(LOCAL_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            source = "local"
        except FileNotFoundError:
            return func.HttpResponse(
                json.dumps({"error": "Cached results not found"}),
                mimetype="application/json",
                status_code=404,
            )

    return func.HttpResponse(
        json.dumps({
            "source": source, 
            "data": data
        }),
        mimetype="application/json",
        status_code=200,
    )
