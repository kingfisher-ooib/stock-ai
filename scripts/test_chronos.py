"""Run an actual Chronos-2 dummy forecast."""

import json
from stock_ai.ai.chronos_model import ChronosModel


def main() -> None:
    values = [100 + i * 0.25 + (i % 5) * 0.1 for i in range(64)]
    print(json.dumps(ChronosModel().predict(values, horizon=5).as_dict()))


if __name__ == "__main__":
    main()
