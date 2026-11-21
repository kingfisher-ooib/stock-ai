"""Run an actual TimesFM 2.5 dummy forecast."""

import json
from stock_ai.ai.timesfm_model import TimesFMModel


def main() -> None:
    values = [100 + i * 0.25 + (i % 5) * 0.1 for i in range(64)]
    print(json.dumps(TimesFMModel().predict(values, horizon=5).as_dict()))


if __name__ == "__main__":
    main()
