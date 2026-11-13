"""Start the dashboard server if it isn't running (scheduled task "Trading Research Dashboard", at sign-in).

So http://localhost:8766/thesis.html is available whenever the user is signed in, without opening the control
panel. Uses the same start path as the panel's "Start app" button; it never refreshes data.
"""
from pathlib import Path

from app_control import ControlError, Controller

if __name__ == "__main__":
    try:
        Controller(Path(__file__).resolve().parent).start()
    except ControlError:
        pass  # e.g. the port belongs to something else; the control panel explains it when opened
