"""Stitch the recorded clips into one finished video.

The cut alternates dark title cards with light live footage, so the piece has a
rhythm rather than being five minutes of somebody scrolling a dashboard. Clips
are joined with short crossfades -- long enough to feel deliberate, short enough
that nobody notices them.

Everything is normalised to 1920x1080 / 30fps / yuv420p first, because the source
clips are variable-frame-rate webm and concatenating those directly produces
audio-less files that some players refuse to seek.

    python3 .video/compose.py            # build out/warrant-pitch.mp4
    python3 .video/compose.py --list     # show the cut with durations
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLIPS = ROOT / "clips"
WORK = ROOT / "work"
OUT = ROOT / "out"

FPS = 30
W, H = 1920, 1080
XFADE = 0.45  # seconds of crossfade between clips

# The cut: clip name, and how long it should be on screen.
#
# Targets are set from how long the narration for that beat takes to read, not
# from how long the clip happened to record. A clip shorter than its target is
# extended by holding its final frame -- a title card has finished animating by
# then and the console is static, so the freeze is invisible and it beats
# re-recording to chase a duration.
CUT: list[tuple[str, float]] = [
    # Five minutes exactly. The live clips are the current product: a real
    # merchant's catalogue, a live model choosing from it, the gate, the record,
    # and a real Razorpay order. The old cut showed a two-pane console that no
    # longer exists and never showed the landing page or the agent at all.
    ("card-01-problem", 20.0),
    ("card-02-holes", 26.0),
    ("live-01-landing", 12.0),
    ("card-03-warrant", 30.0),
    ("live-02-permission", 14.0),
    ("live-03-agent", 26.0),          # the centrepiece: refused, then adapting
    ("live-04-prevents", 16.0),
    ("card-04-boundary", 28.0),
    ("live-05-record-tamper", 18.0),
    ("live-06-evidence-ap2", 16.0),
    ("live-07-razorpay", 12.0),
    ("card-05-results", 20.0),
    ("card-06-losses", 24.0),
    ("card-07-limits", 22.0),
    ("card-08-close", 16.0),
]


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def normalise(src: Path, dst: Path, target: float) -> None:
    """Constant frame rate, fixed size, and held to exactly ``target`` seconds.

    Short clips are padded by cloning the final frame; long ones are trimmed.
    Letterboxed rather than stretched, on the same navy the cards use, so a
    mismatched aspect never shows a black bar against a coloured card.
    """
    have = duration(src)
    pad = max(0.0, target - have)
    chain = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b1526,"
        f"fps={FPS}"
    )
    if pad > 0.05:
        chain += f",tpad=stop_mode=clone:stop_duration={pad:.3f}"
    chain += ",format=yuv420p"

    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
            "-vf", chain, "-t", f"{target:.3f}",
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            str(dst),
        ],
        check=True,
    )


def build(order: list[tuple[str, float]]) -> Path:
    WORK.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    normalised: list[Path] = []
    for name, target in order:
        src = CLIPS / f"{name}.webm"
        if not src.is_file():
            raise SystemExit(f"missing clip: {src}")
        dst = WORK / f"{name}.mp4"
        if not dst.is_file():
            normalise(src, dst, target)
        normalised.append(dst)

    # Chain xfades: each transition overlaps the previous output by XFADE.
    inputs: list[str] = []
    for path in normalised:
        inputs += ["-i", str(path)]

    durations = [duration(p) for p in normalised]
    filters: list[str] = []
    label = "0:v"
    offset = durations[0] - XFADE
    for i in range(1, len(normalised)):
        nxt = f"x{i}"
        filters.append(
            f"[{label}][{i}:v]xfade=transition=fade:duration={XFADE}:"
            f"offset={offset:.3f}[{nxt}]"
        )
        label = nxt
        offset += durations[i] - XFADE

    out = OUT / "warrant-pitch.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error", *inputs,
            "-filter_complex", ";".join(filters),
            "-map", f"[{label}]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "19",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ],
        check=True,
    )
    return out


def main() -> int:
    if not CLIPS.is_dir():
        raise SystemExit("no clips/ directory — run .video/record.py first")

    present = [(n, t) for n, t in CUT if (CLIPS / f"{n}.webm").is_file()]
    missing = [n for n, _ in CUT if (CLIPS / f"{n}.webm") not in
               [CLIPS / f"{p}.webm" for p, _ in present]]

    if "--list" in sys.argv:
        total = 0.0
        for name, target in present:
            have = duration(CLIPS / f"{name}.webm")
            total += target
            kind = "card" if name.startswith("card") else "live"
            hold = f"+{target - have:.1f}s hold" if target > have + 0.05 else ""
            print(f"  {kind:<5} {name:<26} {have:>5.1f}s -> {target:>5.1f}s  {hold}")
        overlap = XFADE * max(0, len(present) - 1)
        final = total - overlap
        print(f"\n  {len(present)} clips · {final:.0f}s "
              f"({int(final // 60)}:{int(final % 60):02d})")
        if missing:
            print(f"  missing: {', '.join(missing)}")
        return 0

    if missing:
        print(f"warning: missing {len(missing)} clip(s): {', '.join(missing)}")

    out = build(present)
    print(f"\n{out}  {out.stat().st_size / 1_000_000:.1f} MB  "
          f"{duration(out):.0f}s ({duration(out) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
