"""Command-line interface for Hugging Face integration."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .chat import ChatSession
from .client import HuggingFaceClient
from .config import load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hf_integration",
        description="Hugging Face Hub / Inference helpers for newAI",
    )
    parser.add_argument("--model", help="Override HF_MODEL")
    parser.add_argument("--token", help="Override HF_TOKEN")
    parser.add_argument("--endpoint", help="Override HF_ENDPOINT (Hub mirror)")
    parser.add_argument("--provider", help="Override HF_PROVIDER (default: auto)")
    parser.add_argument("--timeout", type=float, help="Request timeout seconds")

    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="One-shot or interactive chat completion")
    chat.add_argument("prompt", nargs="?", help="User prompt; omit for interactive REPL")
    chat.add_argument("--system", default="You are a helpful assistant.")
    chat.add_argument("--max-tokens", type=int, default=512)
    chat.add_argument("--temperature", type=float, default=0.7)
    chat.add_argument("--stream", action="store_true")

    gen = sub.add_parser("generate", help="Text generation (completion models)")
    gen.add_argument("prompt")
    gen.add_argument("--max-new-tokens", type=int, default=256)
    gen.add_argument("--temperature", type=float, default=0.7)

    embed = sub.add_parser("embed", help="Create text embeddings")
    embed.add_argument("text", nargs="+", help="One or more texts")
    embed.add_argument("--embed-model", help="Override HF_EMBED_MODEL")

    info = sub.add_parser("model-info", help="Show Hub model metadata")
    info.add_argument("repo_id", nargs="?", help="Model id; default HF_MODEL")

    search = sub.add_parser("search", help="Search models on the Hub")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--pipeline-tag")
    search.add_argument("--sort", default="downloads")

    sub.add_parser("whoami", help="Show authenticated Hub identity")

    return parser


def _client_from_args(args: argparse.Namespace) -> HuggingFaceClient:
    settings = load_settings(
        token=args.token,
        endpoint=args.endpoint,
        model=args.model,
        provider=args.provider,
        timeout=args.timeout,
        embed_model=getattr(args, "embed_model", None),
    )
    return HuggingFaceClient(settings)


def cmd_chat(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    session = ChatSession(
        client,
        system=args.system,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    if args.prompt:
        return _print_chat(session, args.prompt, stream=args.stream)

    print("Interactive chat. Empty line or Ctrl-D to exit.")
    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not prompt:
            return 0
        code = _print_chat(session, prompt, stream=args.stream)
        if code != 0:
            return code


def _print_chat(session: ChatSession, prompt: str, *, stream: bool) -> int:
    try:
        if stream:
            sys.stdout.write("assistant> ")
            sys.stdout.flush()
            for chunk in session.ask(prompt, stream=True):  # type: ignore[union-attr]
                sys.stdout.write(chunk)
                sys.stdout.flush()
            sys.stdout.write("\n")
            return 0

        result = session.ask(prompt, stream=False)
        assert not hasattr(result, "__iter__") or hasattr(result, "content")
        print(f"assistant> {result.content}")  # type: ignore[union-attr]
        return 0
    except Exception as exc:  # noqa: BLE001 - surface API errors to CLI users
        print(f"error: {exc}", file=sys.stderr)
        return 1


def cmd_generate(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    try:
        result = client.generate(
            args.prompt,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(result.text)
    return 0


def cmd_embed(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    try:
        result = client.embed(args.text)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "model": result.model,
                "dimensions": result.dimensions,
                "count": len(result.vectors),
                "vectors": result.vectors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_model_info(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    try:
        info = client.model_info(args.repo_id)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    try:
        models = client.search_models(
            args.query,
            limit=args.limit,
            pipeline_tag=args.pipeline_tag,
            sort=args.sort,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps([m.to_dict() for m in models], ensure_ascii=False, indent=2))
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    client = _client_from_args(args)
    try:
        data = client.whoami()
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


COMMANDS = {
    "chat": cmd_chat,
    "generate": cmd_generate,
    "embed": cmd_embed,
    "model-info": cmd_model_info,
    "search": cmd_search,
    "whoami": cmd_whoami,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    handler = COMMANDS[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
