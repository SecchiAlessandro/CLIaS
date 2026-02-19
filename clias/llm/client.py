"""LiteLLM wrapper for provider-agnostic LLM calls."""

from __future__ import annotations

import base64
from pathlib import Path

from litellm import completion

from clias.config import LLMConfig


class LLMClient:
    """Thin wrapper around LiteLLM providing text and vision calls."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()

    def ask(self, prompt: str, *, system: str | None = None) -> str:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = completion(
            model=self.config.model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return resp.choices[0].message.content

    def ask_with_images(
        self,
        prompt: str,
        image_paths: list[Path],
        *,
        system: str | None = None,
    ) -> str:
        content: list[dict] = [{"type": "text", "text": prompt}]
        for img_path in image_paths:
            data = base64.b64encode(img_path.read_bytes()).decode()
            suffix = img_path.suffix.lstrip(".").lower()
            media_type = f"image/{suffix}" if suffix != "jpg" else "image/jpeg"
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                }
            )
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        resp = completion(
            model=self.config.vision_model,
            messages=messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return resp.choices[0].message.content
