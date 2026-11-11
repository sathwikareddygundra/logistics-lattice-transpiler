"""Child-process entry point for isolated Python execution. Reads a JSON request on
stdin, writes the result frame (orient=split) on stdout, or a JSON error + exit 1."""

from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        import resource

        req = json.loads(sys.stdin.read())
        cpu = int(req["timeout"]) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        from plantdb.plants import get_profile
        from sandbox.runner import SandboxError, _classify, _Conn, exec_python

        profile = get_profile(req["plant"])
        conn = _Conn(profile, req["db_path"], req["timeout"])
        try:
            frame = exec_python(req["code"], conn.read_sql)
        finally:
            conn.close()
        sys.stdout.write(frame.to_json(orient="split", date_format="iso"))
    except Exception as exc:  # noqa: BLE001
        from sandbox.runner import SandboxError, _classify

        err = exc if isinstance(exc, SandboxError) else _classify(exc)
        print(json.dumps({"stage": err.stage, "message": err.message}))
        sys.exit(1)


if __name__ == "__main__":
    main()
