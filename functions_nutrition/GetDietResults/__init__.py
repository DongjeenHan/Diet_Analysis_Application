import json
import os
import azure.functions as func

def main(req: func.HttpRequest) -> func.HttpResponse:
    path = os.environ.get("SIMULATED_NOSQL_PATH", "simulated_nosql/results.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return func.HttpResponse(
            json.dumps({"error": "results not found"}),
            mimetype="application/json",
            status_code=404,
        )

    return func.HttpResponse(
        json.dumps(data),
        mimetype="application/json",
        status_code=200,
    )
