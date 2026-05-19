import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _pop_flag(argv: list[str], *names: str) -> bool:
    found = False
    kept: list[str] = []
    for arg in argv:
        if arg in names:
            found = True
        else:
            kept.append(arg)
    argv[:] = kept
    return found


def _arg_value(argv: list[str], name: str) -> str | None:
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            return argv[index + 1]
        prefix = f"{name}="
        if arg.startswith(prefix):
            return arg[len(prefix):]
    return None


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _looks_like_round3_log(path_text: str | None) -> bool:
    if not path_text:
        return False
    path = Path(path_text)
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return False

    if str(payload.get("round")) == "3":
        return True

    text_fields = [
        str(payload.get("activitiesLog", "")),
        str(payload.get("graphLog", "")),
        json.dumps(payload.get("tradeHistory", [])),
        json.dumps(payload.get("trades", [])),
    ]
    return any("VEV_" in text for text in text_fields)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    force_r3 = _pop_flag(args, "--round3", "--r3")
    force_legacy = _pop_flag(args, "--legacy")
    log_path = _arg_value(args, "--log")

    if not force_legacy and (force_r3 or _looks_like_round3_log(log_path)):
        from prosperity.tooling.r3_log_analysis import run_cli

        return run_cli(args)

    from prosperity.tooling.logs import run_cli

    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
