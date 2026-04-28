import os
import logfire

_initialized = False


def init_logfire() -> bool:
    global _initialized
    if _initialized:
        return True

    token = os.getenv("LOGFIRE_TOKEN")
    if not token:
        return False

    logfire.configure(
        token=token,
        service_name=os.getenv("LOGFIRE_SERVICE_NAME", "outreach-automation"),
        environment=os.getenv("LOGFIRE_ENV", "production"),
        send_to_logfire=True,
    )

    # Auto-instrument all psycopg2 queries — captures SQL + duration as child spans
    try:
        logfire.instrument_psycopg2()
    except Exception:
        pass

    # Auto-instrument all requests HTTP calls — captures Unipile + Sheets calls
    try:
        logfire.instrument_requests()
    except Exception:
        pass

    _initialized = True
    return True
