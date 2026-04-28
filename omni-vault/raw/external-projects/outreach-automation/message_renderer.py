def render_message(template: str, data: dict) -> str:
    """
    Replace {{placeholders}} in template safely.
    Missing values are replaced with empty strings.
    """
    result = template or ""

    for key, value in data.items():
        placeholder = f"{{{{{key}}}}}"
        result = result.replace(placeholder, str(value) if value is not None else "")

    return result.strip()
