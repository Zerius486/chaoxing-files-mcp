import json

import httpx
import pytest

from chaoxing_files.client import ChaoxingClient
from chaoxing_files.config import Settings


@pytest.fixture
def make_client(tmp_path):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps(
            [
                {
                    "name": "session",
                    "value": "secret",
                    "domain": ".chaoxing.com",
                    "path": "/",
                },
            ]
        )
    )
    clients = []

    def factory(handler, limit=1024):
        client = ChaoxingClient(
            Settings(
                cookie_file=cookie_file, download_dir=tmp_path / "out", max_bytes=limit
            ),
            httpx.MockTransport(handler),
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()
