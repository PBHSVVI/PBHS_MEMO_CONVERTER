import re
import sys

UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)

value = sys.argv[1] if len(sys.argv) > 1 else ""
if not UUID.fullmatch(value):
    print("Invalid job_id", file=sys.stderr)
    raise SystemExit(2)

print("job_id accepted")
