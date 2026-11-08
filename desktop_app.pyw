"""No-console entry point for the Windows control panel."""
from pathlib import Path
import traceback

if __name__ == "__main__":
    try:
        from desktop_ui import main
        main()
    except Exception:
        root=Path(__file__).resolve().parent
        (root/"work").mkdir(exist_ok=True)
        detail=traceback.format_exc()
        (root/"work/desktop_error.log").write_text(detail,encoding="utf-8")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,"The control panel could not start. Details were saved to work/desktop_error.log.\n\n"+detail.splitlines()[-1],"Trading Research",0x10)
        except Exception:
            pass
