import argparse

from app.core.assistant import (
    respond,
)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "message"
    )

    parser.add_argument(
        "--project",
        default="t800",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
    )

    args = parser.parse_args()

    result = respond(
        args.message,
        project=args.project,
    )

    print()
    print("=" * 60)
    print("ARKA")
    print("=" * 60)

    if args.debug:

        print(
            "ROTA:",
            result["route"],
        )

        print(
            "MOTIVO:",
            result[
                "route_reason"
            ],
        )

        print()

    print(
        result["answer"]
    )

    if (
        args.debug
        and result["sources"]
    ):

        print()
        print(
            "FONTES:"
        )

        for source in result[
            "sources"
        ]:

            print(
                f"- "
                f"{source.get('source')} "
                f"| "
                f"{source.get('category')} "
                f"| "
                f"{source.get('score', 0):.3f}"
            )

    print()


if __name__ == "__main__":
    main()
