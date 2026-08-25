import os


def get_env(key: str, default=None):
    """
    Read an environment variable stored in lowercase
    with '-' separators instead of '_'.
    """

    return os.environ.get(
        key.lower().replace("_", "-"),
        default,
    )
