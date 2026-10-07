# Stickman Studio

**Write a story. Get a narrated stickman video. Everything runs on your Mac.**

Stickman Studio turns whatever you write (a story, a script, an idea to explain, a poem, rough
notes or just a topic) into a finished short video: a director's plan you can edit, a stick-figure drawing for every shot, a narrator's voice, camera moves,
captions and optional background music, exported as an MP4 for YouTube Shorts, TikTok, Reels or
YouTube.

Nothing is uploaded and there's no account or API key: open-source models do the work, on your Mac.
Optionally, connect a free Cloudflare account to draw shots in seconds instead of about a minute.

## How it works

1. **Write**: anything. Pick vertical (9:16) or wide (16:9), a length (30 s to 3 min), a style (or
   Auto), a narrator, the music, and where to make it (this Mac or Cloudflare).
2. **Review the plan**: an AI director writes a shot-by-shot plan shaped by what you wrote: a
   story is told in order with its dialogue kept, a script keeps its words, a topic gets a hook and
   a payoff. Edit any line, scene, camera move or caption, add or remove shots, or ask for a rewrite.
3. **Make the video**: approve the plan and every shot is drawn, the narration recorded, and the
   video edited together: cuts timed to the voice, camera moves, subtitles, and music that dips
   under the narration. Redraw any shot you don't like; only the changed shots are made again.

## Styles

| Style | Look |
|---|---|
| Classic · Light | Black stick figure on pure white, one red accent |
| Classic · Dark | White stick figure on black, one glowing cyan accent |
| Studio Tech | "Zeke" (red beanie, yellow t-shirt) in a bright studio with floating glass UI |
| Cinematic Story | Zeke in full-colour scenes with cinematic light |
| Storybook | A children's picture book: soft watercolour and pencil on cream paper |
| Comic book | Bold ink lines, flat colours and dramatic angles |

The styles and the explainer arc come from [Stickman Video Director](https://github.com/kaomei/stickman-video-director),
adapted from prompts for a cloud video model to a fully local, image-based pipeline.

## Requirements

- macOS 14+ on Apple silicon, 16 GB of memory or more recommended.
- About 10 GB of disk for the models, downloaded once on first launch (16 GB if you also add Gemma 4 12B).
- Time: on an M3 Pro with 18 GB, a 60-second video takes about 20 minutes. Drawing is the slow part
  (about a minute a shot); planning takes under a minute, the voice seconds, the edit a minute
  or two. You can keep using your Mac meanwhile.

| Model | What it does | Size | Licence |
|---|---|---|---|
| [Qwen3 4B Instruct 2507](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF) (or Gemma 4 12B) | Writes the plan | 2.5 GB | Apache 2.0 |
| [FLUX.2 klein 4B](https://huggingface.co/leejet/FLUX.2-klein-4B-GGUF) | Draws the shots | 7.1 GB with its text encoder and decoder | Apache 2.0 |
| [Kokoro 82M](https://github.com/thewh1teagle/kokoro-onnx) | Reads the narration | 354 MB | Apache 2.0 |

## Build from source

See the [developer guide](docs/dev.md). In short:

```bash
pnpm install
pnpm tauri dev      # needs Rust, cmake and uv
```
