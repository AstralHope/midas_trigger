import argparse


def build_message(name: str, mood: str) -> str:
    """Build a short greeting from the required name and mood inputs."""
    return f"Hello, {name}! You seem {mood}."


def main() -> None:
    parser = argparse.ArgumentParser(description="Demonstrate positional and named script arguments.")
    parser.add_argument("name", help="Name to greet")
    parser.add_argument("--mood", required=True, help="How the person seems")
    options = parser.parse_args()
    print(build_message(options.name, options.mood))


if __name__ == "__main__":
    main()
