"""Stickman Studio's engine: turns a story into a narrated stickman video, all on this Mac.

The app (Tauri) runs this as a sidecar and talks to it over stdin/stdout (`ipc.py`). The heavy
lifting is done by native engines it starts on demand: llama.cpp writes the director's plan,
stable-diffusion.cpp draws each shot with FLUX.2 klein, Kokoro speaks the narration and ffmpeg encodes.
"""
