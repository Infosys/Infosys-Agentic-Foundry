"""Compatibility shim for Vertex AI chat adapter."""

from agentos_model.vertex_chat import (
    ChatVertexAIRaw,
    _autodetect_image_dir,
    _strip_image_data_urls,
)

__all__ = ["ChatVertexAIRaw", "_autodetect_image_dir", "_strip_image_data_urls"]
