# Stickman Studio: developer guide

[← Back to README](../README.md)

## Build and install

Needs macOS 14+ on Apple silicon, Node 22 with pnpm, Rust (stable), `cmake` (for llama.cpp and
stable-diffusion.cpp) and [uv](https://docs.astral.sh/uv/) (for the Python core).

```bash
pnpm install
pnpm tauri build --bundles app
cp -R src-tauri/target/release/bundle/macos/Stickman\ Studio.app /Applications/
```

```bash
pnpm tauri dev           # run with hot reload for the UI
pnpm build:core          # rebuild only the Python core sidecar
pnpm build:engines       # rebuild llama-server and sd-server (only when their versions change)
```

Both `tauri dev` and `tauri build` first build three sidecars into `src-tauri/binaries/`:
- `scripts/build-llama-server.sh` builds llama.cpp's server (static, Metal shaders embedded).
- `scripts/build-sd-server.sh` builds stable-diffusion.cpp's server the same way.
- `scripts/build-core.sh` packs the Python core into one executable with PyInstaller (Python,
  Kokoro's ONNX runtime, Pillow and a static ffmpeg inside). It's skipped when nothing changed.

The core can also be run by hand, which is the quickest way to try a change:

```bash
cd core
STICKMAN_BIN_DIR=../src-tauri/binaries uv run python core_entry.py
{"id": 1, "method": "status"}
```

## Code layout

Three parts: a **Python core** that makes the video, **native engines** it starts on demand, and a
thin **Rust shell** (Tauri) with a **React UI**.

| Path | What it is |
|---|---|
| `core/stickman_core/ipc.py` | The JSON-lines protocol on stdin/stdout; one thread per request, events for progress |
| `core/stickman_core/models.py` | The model catalog (files, sizes, which ones each choice needs), Settings, downloads |
| `core/stickman_core/servers.py` | Starts and stops `llama-server` and `sd-server`; only one is in memory at a time |
| `core/stickman_core/planner.py` | The director: story → plan (title, shots with narration, scene, camera, caption) |
| `core/stickman_core/styles.py` | The visual styles (prompt templates), formats, voices and camera moves |
| `core/stickman_core/voice.py` | Kokoro text to speech |
| `core/stickman_core/render.py` | The edit: timing, cuts and slides, camera moves, captions; encoded with ffmpeg |
| `core/stickman_core/audio.py` | Generated music, whooshes, and the mix with the narration |
| `core/stickman_core/cloud.py` | Optional Cloudflare Workers AI: drawing (FLUX.2 klein 4B) and planning (Gemma 4 26B), token in the Keychain |
| `core/stickman_core/system.py` | Free memory, swap and the biggest apps, for the warning before drawing |
| `core/stickman_core/projects.py` | Videos on disk, incremental production, one job at a time with cancel |
| `src-tauri/src/core.rs` | Starts the core sidecar and relays requests and events |
| `src/views/` | First-run setup, new video, the project (plan editor + video) and Settings |
| `src/lib/api.ts` | Typed calls into the core |

The UI is React 19 + Vite + Tailwind with the same look as Capturita, Murmur and Relay.

## How it works

- **Templates**: "Auto" (the default) has no fixed structure; Story, Inspiration, Explainer, Top
  list, How-to and Poem / Quote are fixed and precise. For a template the app computes the exact
  part of every shot for the chosen length (`planner.outline`, e.g. Intro, Number 3, Number 2,
  Number 1, Outro), gives it to the model and enforces it on the answer: the parts are set in
  code, numbered items and steps get "Number N:" / "Step N:" if the model leaves them out, and a
  poem or quote is split into shots by the app and read exactly as written (the model only
  designs the pictures). Each template also suggests music, captions and pace.
- **Planning**: with Auto, the director isn't tied to one kind of video. The system prompt has it decide
  what the source is and give it that form: a story is told in order with its dialogue word for
  word and its own lesson at the end, a script keeps its words, a topic gets the explainer arc
  (hook → assumption → reveal → insight → takeaway), anything else follows its own shape. It also
  names each shot's part ("Blackout", "The lesson"; a new part gets a slide transition), lists the
  recurring characters with a drawable look, and, with the Auto style, picks the style. The answer
  is forced into a JSON schema (with length caps, so a small model can't loop), exactly one shot
  per ~5.5 s. If the narration comes back much shorter than the length asked for, the model is
  asked once more for fuller lines. The style is never left to the model's wording: each scene is
  wrapped in the style's fixed prompt, plus the look of every character named in it, so the look
  and the characters hold from shot to shot.
- **One engine at a time**: an 18 GB Mac can't hold the story model and the image model together
  (and macOS starts swapping well before that), so the core stops one before starting the other,
  and stops whichever is idle after 10 minutes. The story model is used only while planning.
- **Drawing**: `sd-server` keeps the image model loaded across a whole video. FLUX.2 klein 4B
  (4 steps) draws a 768×1344 shot in about 70 s on an M3 Pro and follows the stick-figure style
  closely. (Z-Image Turbo was tried and dropped: 8 steps, twice as slow, filled silhouettes instead
  of line figures, and at Q8 it pushed an 18 GB Mac into swap.) Every shot of a video uses the same seed, which keeps the drawing
  style consistent; redrawing a shot moves it to another seed.
- **Incremental**: each shot stores the inputs its drawing and voice were made from (a hash of the
  scene, style, format, seed and model; of the line, voice and pace). After edits, only shots
  whose inputs changed are made again, and the video is re-edited only if anything in it changed.
- **Voice**: Kokoro reads each shot's line; the silence it leaves around a line is trimmed, and
  lines are joined with a breath that depends on punctuation (0.32 s after a full stop, 0.1 s when
  the sentence runs on into the next shot), so the voiceover flows instead of stopping and starting.
  Heart, Kokoro's best-rated voice, is the default.
- **Editing**: shots cut on the voice: the picture changes just before the next line starts, with
  a small zoom punch that settles in 0.25 s. Where the story moves to its next stage (hook → twist →
  secret → truth → payoff) the new shot slides in instead, with a whoosh. Within a shot the camera
  drifts along its path (push, pull, pan, rise). Frames are drawn with Pillow from a fractional crop
  box (sub-pixel smooth, unlike ffmpeg's `zoompan`, which jitters) and piped to ffmpeg as raw RGB.
  The video ends by holding the last shot and fading to black with the music.
- **Captions**: one kind at a time. Subtitles show two or three words on a dark pill near the
  bottom, the word being spoken in yellow (word times are estimated from each word's share of the
  line; Kokoro doesn't report them). Key words pop in large near the top. Both are drawn with Pillow.
- **Soundtrack** (`audio.py`): the music is composed in code (pad chords, a plucked arpeggio, a
  bass and a little echo, in three moods), so nothing has to be downloaded or licensed; or the user
  picks a file. The music ducks under the voice (it follows the voice's loudness with a fast attack
  and slow release) and fills the gaps. Everything is mixed with numpy at 48 kHz stereo.
- **Character consistency**: the character is described in every shot's prompt, framed close, and
  every shot uses the same seed. FLUX.2 klein can also take a reference image of the character,
  which would keep it identical, but on an 18 GB Mac that made each shot 2.5x slower and pushed
  macOS into swap, so it isn't used.
- **Image prompts** (`styles.image_prompt`): built in a fixed order, because FLUX weighs what comes
  first: a short "what this is", the scene, who is in it, how every figure is drawn, the look, and
  "no text". In the stickman styles the main character (listed first) always gets the style's
  locked look, and everyone else is "another stick figure drawn the same way, set apart only by"
  an accessory, so a plan that describes a realistic person can't produce a half-human hybrid. The
  director writes each scene as one frozen moment that starts with the shot size and the place.
- **Voices** (`settings.telling`): one narrator, a narrator plus the characters speaking their own
  lines, or the characters only. Each shot has a `speaker`; each character gets a Kokoro voice of
  their gender, different from the narrator's (changeable in the plan's cast list).
- **Several looks at one picture**: a shot with `samePicture` shows the previous shot's drawing
  and isn't drawn; the camera glides (no cut) to `focus_left` / `focus_center` / `focus_right`. The
  planner turns a character's line that follows a picture showing them on one side into such a
  shot, so a conversation cuts between the speakers in one drawing (and draws fewer pictures).
- **Hindi** (`settings.language`): narration, title and captions in Devanagari, scenes and looks
  in English. If the story model writes English anyway (small models do), a second pass translates
  the lines. Pillow here can't lay out Devanagari, so Hindi captions are drawn by ffmpeg's
  HarfBuzz with Devanagari Sangam MN (Kohinoor misplaces the "i" vowel sign there).
- **Plan review** (`planner._review`): the draft is checked in code and sent back with what's
  wrong, up to twice, keeping the version with the fewest problems: the source's dialogue (quoted
  sentences, matched in order) mostly missing, told out of the source's order (it breaks a twist;
  phrases the source repeats are ignored), the narrator reading a character's dialogue in "narrator +
  characters", or a character narrating in the third person in "characters only". What still slips
  through is fixed in code: a character's third-person line goes to the narrator, and a narrator line
  quoting the one character in the picture becomes that character's line. A failed model call is
  retried once, cooler (`planner._ask`).
- **Continuity** (`planner._continuity`): a short, focused question finds changes of look (a
  haircut, an injury, new clothes; not things sold or given away). Every shot then carries each
  character's look before or after the change (`shot["looks"]`, added to the image prompt and the
  image key), and the feature that changes is removed from their lasting look.
- **Stalled drawings** (`servers.Engines._watched_call`): if the image engine's log is silent for
  five minutes (a normal step logs every ~13 s; ~150 s when a nearly empty battery throttles the
  GPU), it is stopped, the core waits for memory to come back and draws again, up to three tries.
  The progress line says when a shot is retried, or when a battery under 10% is slowing drawing.
- **Sharpness**: each frame is cut from the original drawing and resampled once (Lanczos), after a
  light unsharp mask; before, it was enlarged to 1080p and then enlarged again by the camera zoom.
- **Cloud (optional)**: with Cloudflare connected, each video chooses where it's made ("Make it
  on": This Mac, the default, or Cloudflare; stored as `settings.engine`). Cloud shots come out
  simpler than local ones, so it's a speed option. Switching a video redraws its shots on the new
  side (the engine is part of a shot's image key). A Cloudflare video's jobs try Workers AI first. On the first
  failure (free allowance used up, token rejected, offline) the job continues on this Mac, a
  `notice` event warns the user with the reason, and the sidebar shows "Cloud unavailable".
  The voice and the edit always run locally. Cloudflare draws four shots at once; this Mac draws one
  at a time (sd-server's batch only makes variations of one prompt, and two models would swap).
- **Cloud safety refusals**: Cloudflare's filter sometimes "flags" a harmless picture. That's a
  `cloud.Refused`: only that shot is drawn on this Mac, and the rest of the job stays on the cloud.
  Any other failure (allowance used up, token, network) moves the rest of the job to this Mac.
- **Illustrated styles**: besides the stickman styles there are fully illustrated ones (Storybook,
  Comic book). `styles.kind()` tells the director
  whether characters are stick figures or real people (age, hair, clothes), and the Auto style can
  pick them. The prompts describe each look in plain words; no add-on (LoRA) is needed: FLUX.2
  klein draws them well from the description alone.
- **Length**: the director is given a word budget (2.9 words a second) with a hard per-shot cap,
  and if the voiceover still comes back more than 15% long, over-long lines are ended at a
  sentence boundary in code. The new-video page warns when the text is much longer than the
  chosen length (and offers the length that fits); "Rewrite plan" can change the length, which
  rewrites the plan from the original text.
- **Resume**: finished shots and voice lines are saved as they're made, so a video interrupted by
  quitting, a crash or Cancel carries on from where it stopped. The list marks it "Unfinished · N of
  M drawn", the main button says "Resume", and the app reminds you on launch.
- **Send to phone** (`share.py`): a QR code for a link served by the Mac on the local network (a
  page with the video and a Download button, plus the file with range requests so phones can play
  it). The link has a random key, serves that one video only, and stops when the dialog closes,
  after 15 minutes or when the app quits. Nothing goes through the internet.
- **Download**: "Download video…" saves a copy of the finished MP4 wherever the user picks
  (Downloads by default).
- **Before drawing**: if other apps leave less free memory than the image model needs, the app
  says so and names the biggest apps (skipped when drawing in the cloud).
- **Quick preview**: records the voice and renders the full edit with sketch cards in place of
  undrawn shots (`preview.mp4`, about a minute), so the pacing can be judged before drawing.
- **Long jobs**: `caffeinate -i` keeps the Mac awake while a job runs; a notification says when
  the video is ready if the app isn't in front. The story model is unloaded as soon as a plan is
  written, the image model after 3 idle minutes.
- **Leftover models**: if the engine itself crashes or is force-killed, a model server it started
  keeps running (owned by launchd). The engine stops its models on any normal exit, and on every
  start (and before loading a model) it finds and stops leftover copies of its own servers.
- **Side-panel settings**: changes wait as a draft until "Apply changes", which saves them and
  re-makes the video (saying what will be redone); "Discard" drops them. The video and the panel
  never disagree.
- **Quitting**: the app asks the core to stop its engines when it quits; the core also stops them
  if its stdin closes or its parent process disappears, so no model is left holding memory.

## Files

- Models: `~/Library/Application Support/com.stickmanstudio.app/models/`
- Settings: `~/Library/Application Support/com.stickmanstudio.app/settings.json`
- Videos: `~/Movies/Stickman Studio/<id>/` (`project.json`, `shots/`, `voice/`, the MP4)
- Logs: `~/Library/Logs/com.stickmanstudio.app/` (`llama-server.log`, `sd-server.log`, `ffmpeg.log`)
