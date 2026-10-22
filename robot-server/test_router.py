import json
from pathlib import Path

from app.core.router import (
    route_message,
)


ROOT = Path(__file__).resolve().parent

CASES = (
    ROOT
    / "tests"
    / "router_cases.json"
)


def main():

    tests = json.loads(
        CASES.read_text(
            encoding="utf-8"
        )
    )

    passed = 0
    failed = 0

    print()
    print("=" * 68)
    print("ARKA ROUTER TEST")
    print("=" * 68)

    for index, test in enumerate(
        tests,
        start=1,
    ):

        result = route_message(
            test["text"]
        )

        actual = result[
            "route"
        ]

        expected = test[
            "expected"
        ]

        ok = (
            actual == expected
        )

        status = (
            "PASS"
            if ok
            else "FAIL"
        )

        if ok:
            passed += 1
        else:
            failed += 1

        print(
            f"[{index:02d}] "
            f"{status} "
            f"{expected:6s} → "
            f"{actual:6s} | "
            f"{test['text']}"
        )

        if not ok:

            print(
                "     motivo:",
                result["reason"],
            )

    print()
    print(
        f"PASS: {passed}"
    )

    print(
        f"FAIL: {failed}"
    )

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
