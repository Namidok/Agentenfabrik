"""Compile and run small C++ programs in a throwaway folder.

NOT a security boundary: the program runs as you. It gets time, CPU, file-size and
output limits, a clean working folder and a minimal environment, but it could still
read your files or use the network."""
from __future__ import annotations

import os
import re
import resource
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

COMPILE_TIMEOUT = 60
RUN_TIMEOUT = 5
MAX_SOURCE_CHARS = 20_000
MAX_STDIN_CHARS = 10_000
MAX_OUTPUT_CHARS = 4_000
FILE_LIMIT_BYTES = 10 * 1024 * 1024
STANDARD = "c++20"

SIGNAL_HINTS = {
    "SIGSEGV": "invalid memory access",
    "SIGBUS": "invalid memory access",
    "SIGABRT": "aborted, for example by an assert or an uncaught exception",
    "SIGFPE": "arithmetic error such as division by zero",
    "SIGILL": "illegal instruction",
    "SIGXCPU": "used too much CPU time",
    "SIGXFSZ": "wrote too much data",
    "SIGKILL": "killed",
}


class SandboxError(Exception):
    """Expected failure. The message is shown to the model."""


def find_compiler() -> str | None:
    for name in ("clang++", "g++", "c++"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _limits(cpu_seconds: int):
    def apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_LIMIT_BYTES, FILE_LIMIT_BYTES))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def _read_cut(path: Path) -> str:
    size = path.stat().st_size
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read(MAX_OUTPUT_CHARS + 1)
    if len(text) > MAX_OUTPUT_CHARS:
        return text[:MAX_OUTPUT_CHARS].strip() + f"\n...[output cut, about {size} bytes in total]"
    return text.strip()


def _clean(text: str, tmp: str) -> str:
    for variant in {tmp, os.path.realpath(tmp)}:
        text = text.replace(variant + "/", "").replace(variant, "")
    return text


def _run(cmd, cwd, env, timeout, stdin="", cpu_limit=None, label="run"):
    """Run a command with output sent to files, so a chatty program cannot fill memory."""
    out_path = Path(cwd) / f"_{label}_out.txt"
    err_path = Path(cwd) / f"_{label}_err.txt"
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err,
            text=True, start_new_session=True,
            preexec_fn=_limits(cpu_limit) if cpu_limit else None,
        )
        timed_out = False
        try:
            proc.communicate(input=stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # kill the program and anything it started
            except (ProcessLookupError, PermissionError):
                pass
            proc.communicate()
    return proc.returncode, _read_cut(out_path), _read_cut(err_path), timed_out


def _signal_text(number: int) -> str:
    try:
        name = signal.Signals(number).name
    except ValueError:
        return f"signal {number}"
    hint = SIGNAL_HINTS.get(name)
    return f"{name} ({hint})" if hint else name


def run_cpp(code: str, stdin: str = "", run_timeout: int = RUN_TIMEOUT) -> str:
    if not code.strip():
        raise SandboxError("No code was given.")
    if len(code) > MAX_SOURCE_CHARS:
        raise SandboxError(f"The code is too long ({len(code)} characters, limit {MAX_SOURCE_CHARS}).")
    if len(stdin) > MAX_STDIN_CHARS:
        raise SandboxError(f"The input is too long (limit {MAX_STDIN_CHARS} characters).")
    compiler = find_compiler()
    if compiler is None:
        raise SandboxError("No C++ compiler was found. Ask the user to run: xcode-select --install")

    with tempfile.TemporaryDirectory(prefix="agent-cpp-") as tmp:
        (Path(tmp) / "main.cpp").write_text(code, encoding="utf-8")

        compile_env = {**os.environ, "TMPDIR": tmp}
        try:
            rc, out, err, timed_out = _run(
                [compiler, f"-std={STANDARD}", "-Wall", "-Wextra", "-O0", "main.cpp", "-o", "prog"],
                tmp, compile_env, COMPILE_TIMEOUT, label="compile",
            )
        except OSError as e:
            raise SandboxError(f"Could not start the compiler: {e}")
        if timed_out:
            raise SandboxError("Compiling took too long and was stopped.")

        messages = _clean(err or out, tmp)
        if rc != 0:
            if "developer tools" in messages.lower() or "xcode-select" in messages.lower():
                raise SandboxError("The compiler is not set up. Ask the user to run: xcode-select --install")
            return "Compilation failed:\n" + messages

        run_env = {"PATH": "/usr/bin:/bin", "HOME": tmp, "TMPDIR": tmp, "LANG": "C"}
        try:
            rc, out, err, timed_out = _run(
                ["./prog"], tmp, run_env, run_timeout, stdin,
                cpu_limit=run_timeout + 1, label="run",
            )
        except OSError as e:
            raise SandboxError(f"Could not start the program: {e}")

        parts = ["Compiled successfully."]
        if messages:
            parts.append("Compiler warnings:\n" + messages)
        if timed_out:
            parts.append(f"The program was stopped after {run_timeout} seconds (time limit).")
        elif rc < 0:
            parts.append(f"The program crashed with {_signal_text(-rc)}.")
        else:
            parts.append(f"The program finished with exit code {rc}.")
        out, err = _clean(out, tmp), _clean(err, tmp)
        if out:
            parts.append("Output:\n" + out)
        if err:
            parts.append("Error output:\n" + err)
        if not out and not err:
            parts.append("(the program printed nothing)")
        return "\n".join(parts)



# ---- checking whether a C++ name exists ----

_NAME_RE = re.compile(r"(::)?[A-Za-z_]\w*(::[A-Za-z_]\w*)*")
_HEADER_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./+-]*")
_MISSING_MARKERS = (
    "no member named", "has not been declared", "is not a member of",
    "undeclared identifier", "unknown namespace", "not declared",
)
STD_HEADERS = """
algorithm any array atomic bit bitset cassert cctype cerrno cfloat chrono cinttypes climits
clocale cmath compare complex concepts condition_variable csetjmp csignal cstdarg cstddef
cstdint cstdio cstdlib cstring ctime cwchar cwctype deque exception filesystem forward_list
fstream functional future initializer_list iomanip ios iosfwd iostream istream iterator limits
list locale map memory memory_resource mutex new numbers numeric optional ostream queue random
ranges ratio regex scoped_allocator set shared_mutex source_location span sstream stack
stdexcept streambuf string string_view system_error thread tuple type_traits typeindex
typeinfo unordered_map unordered_set utility valarray variant vector version
""".split()


def _using_check(compiler: str, name: str, include_lines: list[str]) -> tuple[int, str]:
    """Compile 'using <name>;' after the given includes. Returns (exit code, cleaned messages)."""
    source = "\n".join(include_lines) + f"\nusing {name};\nint main() {{}}\n"
    with tempfile.TemporaryDirectory(prefix="agent-cpp-") as tmp:
        (Path(tmp) / "main.cpp").write_text(source, encoding="utf-8")
        try:
            rc, out, err, timed_out = _run(
                [compiler, f"-std={STANDARD}", "-fsyntax-only", "main.cpp"],
                tmp, {**os.environ, "TMPDIR": tmp}, COMPILE_TIMEOUT, label="compile",
            )
        except OSError as e:
            raise SandboxError(f"Could not start the compiler: {e}")
        if timed_out:
            raise SandboxError("Checking took too long and was stopped.")
        return rc, _clean(err or out, tmp)


def _classify(rc: int, messages: str, header: str = "") -> tuple[str, str]:
    if rc == 0:
        return "FOUND", ""
    short = "\n".join(messages.splitlines()[:6])
    lowered = messages.lower()
    if header and ("file not found" in lowered or "no such file" in lowered):
        return "HEADER MISSING", short
    if any(m in lowered for m in _MISSING_MARKERS):
        return "NOT FOUND", short
    return "COULD NOT CHECK", short


def check_cpp_name(name: str, header: str = "") -> str:
    """Is a qualified C++ name (like std::vector) declared? Answered by compiling a using-declaration.
    Without a header: tests the standard library headers. With a header: tests that header
    on its own, and also reports what the standard library headers alone give."""
    name = (name or "").strip()
    header = (header or "").strip()
    if header.startswith("<") and header.endswith(">"):
        header = header[1:-1].strip()
    if not _NAME_RE.fullmatch(name) or "::" not in name:
        raise SandboxError("Give a qualified C++ name such as std::vector or ::getopt.")
    if header and (".." in header or not _HEADER_RE.fullmatch(header)):
        raise SandboxError("The header must be a plain file name such as unistd.h or vector.")
    compiler = find_compiler()
    if compiler is None:
        raise SandboxError("No C++ compiler was found. Ask the user to run: xcode-select --install")

    std_includes = [f"#if __has_include(<{h}>)\n#include <{h}>\n#endif" for h in STD_HEADERS]
    caveat = (
        f"(Checked with -std={STANDARD} against this computer's headers, "
        "which are not the same as the language standard.)"
    )
    rc, msgs = _using_check(compiler, name, std_includes)
    std_verdict, std_short = _classify(rc, msgs)

    if not header:
        if std_verdict == "FOUND":
            return f"FOUND: {name} is declared in the standard library headers. {caveat}"
        if std_verdict == "NOT FOUND":
            return (
                f"NOT FOUND: {name} is not declared in the standard library headers. {caveat}\n"
                f"Compiler message:\n{std_short}"
            )
        return f"COULD NOT CHECK: the test program failed for another reason.\nCompiler message:\n{std_short}"

    rc, msgs = _using_check(compiler, name, [f"#include <{header}>"])
    verdict, short = _classify(rc, msgs, header)
    if verdict == "FOUND":
        first = f"FOUND: {name} is declared when only <{header}> is included."
    elif verdict == "HEADER MISSING":
        first = f"HEADER MISSING: <{header}> does not exist on this computer.\nCompiler message:\n{short}"
    elif verdict == "NOT FOUND":
        first = f"NOT FOUND: {name} is not declared by <{header}> alone.\nCompiler message:\n{short}"
    else:
        first = f"COULD NOT CHECK: the test program failed for another reason.\nCompiler message:\n{short}"
    return f"{first}\nStandard library headers alone: {std_verdict}.\n{caveat}"
