import os
import re
from pathlib import Path
from typing import Literal

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

from sre_gateway.llm.embeddings import hash_embedding

_ENV_RE = re.compile(r"\$\{(\w+)\}")


class TierConfig(BaseModel):
    provider: Literal["vertex-gemini", "vertex-anthropic", "openai-compatible", "fake"]
    model: str
    params: dict = Field(default_factory=dict)
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"


class EmbeddingsConfig(BaseModel):
    provider: Literal["vertex", "openai-compatible", "fake"]
    model: str
    dim: int = 768
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"


class ModelsConfig(BaseModel):
    tiers: dict[str, TierConfig]
    embeddings: EmbeddingsConfig
    holmes: dict[str, str] = Field(default_factory=dict)
    pricing: dict[str, dict] = Field(default_factory=dict)
    vertex: dict = Field(default_factory=dict)
    script_dir: str | None = None


def load_models_config(path: Path) -> ModelsConfig:
    raw = path.read_text()
    raw = _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), raw)
    return ModelsConfig.model_validate(yaml.safe_load(raw))


class ModelFactory:
    def __init__(self, config: ModelsConfig, script_dir: Path | None = None) -> None:
        self.config = config
        self.script_dir = script_dir or Path(config.script_dir or "tests/fixtures/scripts")

    def chat(self, tier: str, node: str) -> BaseChatModel:
        tc = self.config.tiers[tier]
        if tc.provider == "fake":
            from sre_gateway.llm.scripted import ScriptedChatModel

            return ScriptedChatModel(node=node, script_dir=self.script_dir)
        if tc.provider == "vertex-gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=tc.model, vertexai=True,
                project=self.config.vertex.get("project"),
                location=self.config.vertex.get("location"), **tc.params)
        if tc.provider == "vertex-anthropic":
            from langchain_google_vertexai.model_garden import ChatAnthropicVertex

            return ChatAnthropicVertex(
                model_name=tc.model,
                project=self.config.vertex.get("project"),
                location=self.config.vertex.get("location"), **tc.params)
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=tc.model, base_url=tc.base_url,
                          api_key=os.environ.get(tc.api_key_env, "unused"), **tc.params)

    def describe(self, tier: str) -> tuple[str, tuple[float, float]]:
        tc = self.config.tiers[tier]
        p = self.config.pricing.get(tc.model, {})
        return tc.model, (float(p.get("input", 0.0)), float(p.get("output", 0.0)))

    def holmes_model(self, tier: str) -> str:
        return self.config.holmes[tier]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ec = self.config.embeddings
        if ec.provider == "fake":
            return [hash_embedding(t, ec.dim) for t in texts]
        if ec.provider == "vertex":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            emb = GoogleGenerativeAIEmbeddings(
                model=ec.model, vertexai=True,
                project=self.config.vertex.get("project"),
                location=self.config.vertex.get("location"),
                output_dimensionality=ec.dim)
            return await emb.aembed_documents(texts)
        from langchain_openai import OpenAIEmbeddings

        emb = OpenAIEmbeddings(model=ec.model, base_url=ec.base_url,
                               api_key=os.environ.get(ec.api_key_env, "unused"),
                               dimensions=ec.dim)
        return await emb.aembed_documents(texts)
