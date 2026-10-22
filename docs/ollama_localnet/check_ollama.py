"""Probe a remote Ollama server: list models, switch models, large prompts, image extraction.

Usage:
    python check_ollama.py list
    python check_ollama.py models  [--models llama3.2:3b granite4:3b] [--prompt "..."]
    python check_ollama.py large   [--model M] [--words 20000] [--num-ctx 32768]
    python check_ollama.py image   IMAGE_PATH --model VISION_MODEL [--prompt "..."]
    python check_ollama.py all     [--image IMAGE_PATH --vision-model M]

Host: --host or OLLAMA_HOST (default http://192.168.1.106:11434). Stdlib only.

Examples:
    # list installed models
    python check_ollama.py list

    # use another host
    python check_ollama.py --host http://localhost:11434 list
    OLLAMA_HOST=http://10.0.0.5:11434 python check_ollama.py list

    # same prompt on specific models (default: the first three installed)
    python check_ollama.py models --models llama3.2:3b granite4:3b gemma3:4b
    python check_ollama.py models --models qwen2.5:7b-instruct --prompt "Translate 'hello' to Spanish."

    # large prompt: ~16k tokens, then ~40k tokens with a bigger context window
    python check_ollama.py large --words 8000
    python check_ollama.py large --model granite4:3b --words 20000 --num-ctx 65536

    # extract data from an image (vision models: qwen2.5vl:3b, qwen2.5vl:7b, granite3.2-vision:2b)
    python check_ollama.py image invoice.jpg --model qwen2.5vl:7b --num-ctx 65536
    python check_ollama.py image invoice.png --model qwen2.5vl:3b \\
        --prompt "Return JSON with keys: invoice_number, date, total."

    # everything, including the image step
    python check_ollama.py all --image invoice.png --vision-model qwen2.5vl:7b
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_HOST = "http://192.168.1.106:11434"
DEFAULT_MODEL = "llama3.2:3b"
TIMEOUT_S = 600  # TODO: [MVP] per-call timeout policy


def call(host: str, path: str, body: dict | None = None) -> dict:
    """Send a GET (no body) or JSON POST to the Ollama API and return the decoded reply."""
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{host}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310
        return json.load(resp)


def list_models(host: str) -> list[str]:
    """Print and return the model names installed on the server."""
    models = call(host, "/api/tags")["models"]
    for model in models:
        details = model["details"]
        caps = ",".join(model.get("capabilities", []))
        print(
            f"  {model['name']:<32} {details['parameter_size']:>7} "
            f"{details['quantization_level']:<8} {model['size'] / 1e9:5.1f} GB  [{caps}]"
        )
    return [model["name"] for model in models]


def generate(host: str, model: str, prompt: str, options: dict | None = None) -> dict:
    """Run one non-streaming /api/generate call and print a short timing summary."""
    start = time.perf_counter()
    reply = call(
        host,
        "/api/generate",
        {"model": model, "prompt": prompt, "stream": False, "options": options or {}},
    )
    elapsed = time.perf_counter() - start
    print(
        f"  [{model}] {elapsed:.1f}s wall, prompt_tokens={reply.get('prompt_eval_count')}, "
        f"output_tokens={reply.get('eval_count')}"
    )
    return reply


def check_models(host: str, models: list[str], prompt: str) -> None:
    """Send the same prompt to several models and show each answer."""
    for model in models:
        reply = generate(host, model, prompt)
        print(f"    -> {reply['response'].strip()[:200]!r}")


def check_large(host: str, model: str, words: int, num_ctx: int) -> None:
    """Send a long prompt with a hidden fact at the start and check the model recalls it."""
    filler = " ".join(f"lorem{i % 97}" for i in range(words))
    prompt = (
        "The secret code is PINEAPPLE-42.\n"
        f"{filler}\n"
        "Question: what is the secret code? Answer with the code only."
    )
    reply = generate(host, model, prompt, {"num_ctx": num_ctx})
    answer = reply["response"].strip()
    print(f"    -> {answer[:200]!r}  recalled={'PINEAPPLE-42' in answer}")
    # TODO: [MVP] a prompt_eval_count near num_ctx means silent truncation; assert on it


def check_image(
    host: str, model: str, image: Path, prompt: str, num_ctx: int = 16384
) -> None:
    """Send an image to a vision model through /api/chat and print the extracted data."""
    encoded = base64.b64encode(image.read_bytes()).decode()
    start = time.perf_counter()
    reply = call(
        host,
        "/api/chat",
        {
            "model": model,
            "stream": False,
            "format": "json",
            "options": {"num_ctx": num_ctx},
            "messages": [{"role": "user", "content": prompt, "images": [encoded]}],
        },
    )
    print(
        f"  [{model}] {time.perf_counter() - start:.1f}s wall, "
        f"done_reason={reply.get('done_reason')}, "
        f"prompt_tokens={reply.get('prompt_eval_count')}, "
        f"output_tokens={reply.get('eval_count')}, num_ctx={num_ctx}"
    )
    if reply.get("done_reason") == "length":
        print("  WARNING: output truncated (context full); raise --num-ctx")
    print(reply["message"]["content"])


def parse_args() -> argparse.Namespace:
    """Build the CLI."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    models = sub.add_parser("models")
    models.add_argument("--models", nargs="+")
    models.add_argument("--prompt", default="In one sentence: why is the sky blue?")
    large = sub.add_parser("large")
    large.add_argument("--model", default=DEFAULT_MODEL)
    large.add_argument("--words", type=int, default=20000)
    large.add_argument("--num-ctx", type=int, default=32768)
    image = sub.add_parser("image")
    image.add_argument("image", type=Path)
    image.add_argument("--model", required=True)
    image.add_argument("--num-ctx", type=int, default=16384)
    image.add_argument(
        "--prompt",
        default="Extract all visible fields (dates, names, totals) as a JSON object.",
    )
    every = sub.add_parser("all")
    every.add_argument("--image", type=Path)
    every.add_argument("--vision-model")
    return parser.parse_args()


def main() -> int:
    """Run the requested check."""
    args = parse_args()
    host = args.host.rstrip("/")
    print(f"Host: {host}")
    if args.cmd in ("list", "models", "all"):
        print("== list models")
        names = list_models(host)
    if args.cmd in ("models", "all"):
        print("== different models")
        prompt = getattr(args, "prompt", "In one sentence: why is the sky blue?")
        check_models(host, getattr(args, "models", None) or names[:3], prompt)
    if args.cmd in ("large", "all"):
        print("== large prompt")
        model = getattr(args, "model", DEFAULT_MODEL)
        words = getattr(args, "words", 20000)
        num_ctx = getattr(args, "num_ctx", 32768)
        check_large(host, model, words, num_ctx)
    if args.cmd == "image":
        print("== image extraction")
        check_image(host, args.model, args.image, args.prompt, args.num_ctx)
    if args.cmd == "all" and args.image and args.vision_model:
        print("== image extraction")
        check_image(
            host, args.vision_model, args.image, "Extract all visible fields as JSON."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
