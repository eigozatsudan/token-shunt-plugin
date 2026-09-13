def greet(name):
    """Return a greeting for name; empty raises ValueError."""
    if name == "":
        raise ValueError("name must not be empty")
    return f"Hello, {name}!"
