"""Run one real OpenAI request through the synchronous inference API."""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceConfig,
    InferenceException,
    InferenceOrchestrator,
    InferenceRequest,
    ModelConfig,
)


def main() -> int:
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("Set OPENAI_API_KEY in .env or the process environment.", file=sys.stderr)
        return 2

    config = InferenceConfig(
        models=[
            ModelConfig(
                config_id="openai-quickstart",
                provider="openai",
                model="gpt-4.1-nano",
            )
        ],
        batch_size=1,
    )
    requests = [
        InferenceRequest(
            request_id="quickstart-sync",
            prompt="Reply with exactly: HELLO_AUDITKIT",
            system_prompt="Follow the requested output format exactly.",
            model_config_id="openai-quickstart",
            metadata={"example": "sync"},
        )
    ]
    inference = InferenceOrchestrator(EDSLAdapter())

    try:
        preview = inference.preview_batch(requests, config)
        for rendered in preview.prompts:
            print(f"Preview for {rendered.request_id}: {rendered.user_prompt}")

        for batch in inference.run_batches(requests, config):
            print(
                f"Completed batch {batch.batch_number}/{batch.total_batches} "
                f"in {batch.elapsed_seconds:.2f}s"
            )
            for result in batch.results:
                if result.error is not None:
                    print(
                        f"{result.request_id} failed: "
                        f"{result.error.type}: {result.error.message}",
                        file=sys.stderr,
                    )
                    return 1
                print(f"{result.request_id}: {result.content}")
    except InferenceException as error:
        print(f"Inference stopped: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
