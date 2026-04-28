import os
import rollbar

_initialized = False


def init_rollbar() -> bool:
    global _initialized
    if _initialized:
        return True

    token = os.getenv("ROLLBAR_ACCESS_TOKEN")
    if not token:
        return False

    rollbar.init(
        token,
        os.getenv("ROLLBAR_ENV", "production"),
        code_version=os.getenv("ROLLBAR_CODE_VERSION", "1.0"),
        server_root=os.getenv("ROLLBAR_SERVER_ROOT", ""),
        allow_logging_basic_config=False,
    )
    _initialized = True
    return True
