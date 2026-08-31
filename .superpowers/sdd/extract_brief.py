from pathlib import Path
import sys

plan = Path(sys.argv[1])
n = sys.argv[2]
out = Path(sys.argv[3])
heading = f"### Task {n}:"
text = plan.read_text(encoding="utf-8")
lines = text.splitlines(keepends=True)
infence = False
intask = False
buf = []
for line in lines:
    if line.lstrip().startswith("```"):
        infence = not infence
        if intask:
            buf.append(line)
        continue
    if not infence and line.startswith("### Task "):
        intask = line.startswith(heading)
        if not intask and buf:
            break
        if intask:
            buf.append(line)
        continue
    if intask:
        buf.append(line)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("".join(buf), encoding="utf-8")
print(f"wrote {out} ({len(buf)} lines)")
