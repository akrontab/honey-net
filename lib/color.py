import sys


def _enable_ansi():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


_COLOR = sys.stdout.isatty()
_enable_ansi()


def _c(code, text): return f"\033[{code}m{text}\033[0m" if _COLOR else text
def green(t):  return _c("32;1", t)
def red(t):    return _c("31;1", t)
def yellow(t): return _c("33;1", t)
def gray(t):   return _c("2", t)
def bold(t):   return _c("1", t)
