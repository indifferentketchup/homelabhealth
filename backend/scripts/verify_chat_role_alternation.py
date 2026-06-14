"""Verify chat message normalization for strict user/assistant templates.

Run from project root:
    docker exec hlh_api python scripts/verify_chat_role_alternation.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.prompt_assembly import _normalize_messages_for_inference


def check(label: str, cond: bool) -> None:
    if not cond:
        print(f"FAIL  {label}")
        sys.exit(1)
    print(f"PASS  {label}")


def main() -> None:
    merged_users = _normalize_messages_for_inference(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "retry a"},
            {"role": "user", "content": "retry b"},
        ]
    )
    check(
        "consecutive user turns merge",
        merged_users
        == [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "retry a\n\nretry b"},
        ],
    )

    leading_assistant = _normalize_messages_for_inference(
        [{"role": "assistant", "content": "orphan"}]
    )
    check(
        "leading assistant gets synthetic user prefix",
        len(leading_assistant) == 2
        and leading_assistant[0]["role"] == "user"
        and leading_assistant[1]["role"] == "assistant",
    )

    system_merge = _normalize_messages_for_inference(
        [
            {"role": "system", "content": "a"},
            {"role": "system", "content": "b"},
            {"role": "user", "content": "hi"},
        ]
    )
    check(
        "consecutive system blocks merge",
        system_merge[0]["role"] == "system" and "a" in system_merge[0]["content"] and "b" in system_merge[0]["content"],
    )

    print("\nAll chat role alternation checks PASS.")


if __name__ == "__main__":
    main()
