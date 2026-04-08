import argparse

from doomgame.game import DoomGame


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dev-mode",
        action="store_true",
        help="Start directly on level 5 with immortality enabled.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.dev_mode:
        DoomGame(dev_start_level=5, dev_immortal=True, dev_auto_difficulty="hard").run()
    else:
        DoomGame().run()
