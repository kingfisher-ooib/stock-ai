"""Measure local Qwen latency and generation speed on a short fixed prompt."""

import json
import time

from openai import OpenAI
from transformers import AutoTokenizer

from stock_ai.config import Settings, require_local_url


def main() -> None:
    settings = Settings()
    client = OpenAI(base_url=require_local_url(settings.mlx_base_url),
                    api_key="local", timeout=120, max_retries=0)
    start = time.perf_counter()
    first = None
    pieces = []
    stream = client.chat.completions.create(
        model=settings.mlx_model,
        messages=[{"role": "user", "content": "List the integers from 1 through 100, separated by commas, without other text."}],
        max_tokens=512, temperature=0, stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        content = chunk.choices[0].delta.content
        if content:
            first = first or time.perf_counter()
            pieces.append(content)
    end = time.perf_counter()
    if first is None:
        raise RuntimeError("No streamed content from local model")
    output = "".join(pieces)
    tokenizer = AutoTokenizer.from_pretrained(settings.mlx_model)
    tokens = len(tokenizer.encode(output, add_special_tokens=False))
    print(json.dumps({
        "device": "mlx/Metal", "model": settings.mlx_model,
        "first_content_seconds": round(first - start, 3),
        "total_seconds": round(end - start, 3),
        "output_tokens": tokens,
        "generation_tokens_per_second": round(tokens / max(end - first, 1e-9), 2),
        "output": output,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
