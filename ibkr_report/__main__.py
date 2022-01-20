from ibkr_report import create_app, definitions


def main() -> None:
    app = create_app()
    app.run(host="127.0.0.1", port=8080, debug=definitions.DEBUG)


if __name__ == "__main__":
    main()
