import logging


def configure_logging(verbose=False):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s", force=True)
