from math import ceil


reset = "\033[0m"
bold = "\033[1m"

blue = "\033[94m"
green = "\033[32m"
yellow = "\033[93m"
red = "\033[91m"
gray = "\033[90m"

header = "\033[95m"
ok_blue = bold + blue + "[+]" + reset
info = bold + green + "[i]" + reset
warning = bold + yellow + "[!]" + reset
fail = bold + red + "[!]" + reset + " Error:"

uline = "\033[4m"

PROGRESS_BAR_CHAR = "\u2501"  # \u2585
CLEAN_LINE = "\x1b[1A\x1b[2K"


def print_info(message: str, sep: str = " ", end: str = "\n") -> None:
    print(info + " " + message, sep=sep, end=end)


def print_ok(message: str, sep: str = " ", end: str = "\n") -> None:
    print(ok_blue + " " + message, sep=sep, end=end)


def print_err(message: str, sep: str = " ", end: str = "\n") -> None:
    print(fail + " " + message, sep=sep, end=end)


def print_warn(message: str, sep: str = " ", end: str = "\n") -> None:
    print(warning + " " + message, sep=sep, end=end)


def print_progress_bar(i: int, max: int, length: int, end: str = "\r"):
    adj_index = ceil((i + 1) / max * length)
    print_info("", end="")
    print(PROGRESS_BAR_CHAR * (adj_index) + " " * (length - adj_index), end=" ")
    print(f"{i+1} of {max}", end=end)


def print_progress_percent(i: int, length, end: str = "\r"):
    adj_index = ceil(i / 100 * length)
    print_info("", end="") if i < 100 else print_ok("", end=blue)
    print(PROGRESS_BAR_CHAR * (adj_index) + " " * (length - adj_index), end=" ")
    print(f"{i}%" + reset, end=end)


def sizeof_fmt(num, suffix="B"):
    for unit in ("", "K", "M", "G", "T", "P", "E", "Z"):
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f} Y{suffix}"
