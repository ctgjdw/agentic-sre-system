from pathlib import Path

from sre_gateway.environment import load_environment

CONFIG_DIR = Path(__file__).parents[2] / "config"


def test_environment_descriptor_renders_prompt_block():
    env = load_environment(CONFIG_DIR / "environment.yaml")
    assert env.name == "spectre" and env.platform == "docker-compose"
    assert "keycloak" in env.all_containers()
    block = env.prompt_block()
    assert "Target environment 'spectre'" in block
    assert "spectre-opensearch" in block and "cluster health" in block
