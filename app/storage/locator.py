from pathlib import Path


AZURE_SCHEME = "azure://"


def is_azure_locator(locator: str) -> bool:
    return locator.startswith(AZURE_SCHEME)


def locator_filename(locator: str) -> str:
    if is_azure_locator(locator):
        return locator.rsplit("/", 1)[-1]

    return Path(locator).name


def locator_stem(locator: str) -> str:
    return Path(locator_filename(locator)).stem


def locator_extension(locator: str) -> str:
    return Path(locator_filename(locator)).suffix.lower()


def azure_locator(container: str, blob_name: str) -> str:
    return f"{AZURE_SCHEME}{container}/{blob_name.lstrip('/')}"


def parse_azure_locator(locator: str) -> tuple[str, str]:
    if not is_azure_locator(locator):
        raise ValueError(
            f"Not an Azure blob locator: {locator}"
        )

    remainder = locator[len(AZURE_SCHEME):]
    container, _, blob_name = remainder.partition("/")

    if not container or not blob_name:
        raise ValueError(
            f"Invalid Azure blob locator: {locator}"
        )

    return container, blob_name
