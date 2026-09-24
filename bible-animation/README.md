# The Story of the Bible (animated)

`the_story_of_the_bible.mp4`: a **56.5-second, 1920×1080, 24 fps** animated overview of the Bible,
from Creation to New Creation, with a synthesized ambient soundtrack.

| # | Scene | Reference |
|---|-------|-----------|
| 0 | Title | |
| 1 | In the beginning, God created | Genesis 1–2 |
| 2 | Sin breaks the world | Genesis 3 |
| 3 | The Flood and a promise | Genesis 6–9 |
| 4 | A promise to Abraham | Genesis 12–22 |
| 5 | Rescued from slavery (Red Sea) | Exodus 14 |
| 6 | Kings, prophets & the temple | 1 Samuel – Malachi |
| 7 | Jesus, the Savior, is born | Luke 2 |
| 8 | He teaches, heals & forgives | Matthew – John |
| 9 | He gave His life for us | John 19 · Romans 5:8 |
| 10 | He is risen! | Matthew 28 · 1 Corinthians 15 |
| 11 | The Good News spreads | Acts – Jude |
| 12 | All things made new | Revelation 21–22 |

A timeline across the top tracks where each scene sits in the overall story.

## Animation techniques

Every frame is drawn in code with Cairo. There are no image assets.

- **Easing** on all motion (slow-in/slow-out), with **overshoot** for things that pop in (sun, stars, trees, flowers)
- **Anticipation**: the first light pulls inward before it bursts, Moses dips his staff before raising it, and the tomb stone rocks back before it rolls
- **Squash & stretch**: the falling fruit and the dropping crown squash when they land
- **Overlapping action / follow-through**: title letters, temple columns, the crowd and the Red Sea walkers all start at staggered times
- **Secondary motion**: rain, drifting leaves, swaying trees, birds, water shimmer and floating light motes
- **Physically driven motion**: the ark tilts to match the slope of the wave under it, and the stone turns by distance ÷ radius, so it rolls instead of sliding
- **Camera and staging**: slow push-ins, pull-backs and tilts, cross-dissolves between scenes, film grain and a vignette

## Re-rendering

```bash
pip install pycairo numpy imageio-ffmpeg
python3 render.py                    # writes the_story_of_the_bible.mp4 (about 3 minutes on 4 cores)
python3 render.py --preview 5 22 45  # writes still PNGs at those times into preview/
```

The script installs the bundled Cinzel and EB Garamond fonts (SIL OFL, see `fonts/`) into `~/.fonts`.
If they aren't available, it falls back to FreeSerif.
