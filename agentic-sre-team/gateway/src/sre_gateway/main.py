import uvicorn

from sre_gateway.api.app import create_app
from sre_gateway.settings import get_settings

app = create_app()

if __name__ == "__main__":
    uvicorn.run("sre_gateway.main:app", host="0.0.0.0", port=get_settings().api_port)
