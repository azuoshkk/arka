import argparse

from app.agents.expert import (
    answer,
)


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "question"
    )

    parser.add_argument(
        "--project",
        default="t800",
    )

    args = parser.parse_args()

    result = answer(
        question=args.question,
        project=args.project,
    )

    print()
    print("=" * 60)
    print("ARKA")
    print("=" * 60)
    print()

    print(
        result["answer"]
    )

    if result["sources"]:

        print()
        print("FONTES RECUPERADAS:")

        for source in result["sources"]:

            page = (
                f" página {source['page']}"
                if source["page"]
                else ""
            )

            print(
                f"[Fonte {source['number']}] "
                f"{source['source']}"
                f"{page} "
                f"(score={source['score']:.3f})"
            )

    print()


if __name__ == "__main__":
    main()
