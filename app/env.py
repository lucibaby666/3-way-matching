import os


def get_env(key: str, default=None):
    """
    Read an environment variable. Checks:
    1. Exact key as provided (e.g. FOUNDRY_OPENAI_BASE_URL)
    2. Uppercase key with '_'
    3. Lowercase key with '-' (e.g. foundry-openai-base-url)
    4. Default value if not found
    """
    val = os.environ.get(key)
    if val is not None:
        return val

    val = os.environ.get(key.upper())
    if val is not None:
        return val

    val = os.environ.get(key.lower().replace("_", "-"))
    if val is not None:
        return val

    return default
