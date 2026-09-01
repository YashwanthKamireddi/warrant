# Pitch video

The five-minute video is built, not performed. Recording a live demo means
fumbling a click on take nine; this records the console being driven
deterministically, cuts it against title cards, and leaves only the narration to
you.

```bash
uv run warrant serve --port 8899 &
uv run python .video/record.py          # ~4 min, writes clips/
python3 .video/compose.py --list        # the cut, with durations
python3 .video/compose.py               # writes out/warrant-pitch.mp4
```

Then open `out/warrant-pitch.mp4`, hit play, and read [NARRATION.md](NARRATION.md)
over it.

## What is source and what is output

| | |
| --- | --- |
| `scenes/*.html` | the eight title cards — source, committed |
| `record.py` | drives the console and captures footage — source |
| `compose.py` | the cut order and the crossfade chain — source |
| `NARRATION.md` | word-for-word, timed to the cut — source |
| `clips/`, `work/`, `out/` | build output — gitignored |

## Two decisions worth knowing

**The console is recorded at a 1440×810 viewport upscaled to 1920×1080.** Capturing
a 1580px-wide interface at native 1080p makes 13px UI text unreadable on the laptop
where this will actually be watched. The upscale trades pixel purity for legibility,
which is the right trade for a pitch.

**Dark title cards alternate with light live footage.** It gives the cut a rhythm
instead of five minutes of somebody scrolling a dashboard, and the cards use the
product's own navy, bronze and type — a title card that looks like different
software than the demo it introduces reads as a template.
