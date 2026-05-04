import os
from pathlib import Path

from fastapi import FastAPI

SYNAPSE_DIR = Path(os.environ["SYNAPSE_DIR"])

app = FastAPI(title="S-Deck")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "synapse_dir": str(SYNAPSE_DIR)}
