"""Visual styles, formats and voices.

The styles follow the Stickman Video Director skill's catalog. The look and the character are
locked here, in code, and wrapped around every shot's scene description, so a small story model
only has to describe what happens; it can't drift the drawing style from shot to shot.
"""

import re

# Every prompt is built in the same order, because FLUX pays most attention to what comes first:
# a short "what this is", then the scene (what happens), then who is in it, then the look.
# "people" says how every figure is drawn; "hero" is the locked look of the main character in the
# stickman styles, so the story model only has to say what happens and can't drift the character.
STYLES = {
    "classic-light": {
        "name": "Classic · Light",
        "note": "Black stick figure on a pure white canvas, one bold accent colour.",
        "intro": "A minimalist stick figure illustration.",
        "hero": "a stick figure with a hollow circular head with no face, a single straight line for a body and thin straight black line limbs",
        "people": "Every person is a simple black stick figure with a hollow round head and thin uniform line limbs, no realistic hair or clothing, no realistic hands; figures are drawn large and close.",
        "look": (
            "Bold clean black vector linework of uniform medium weight on a perfectly flat pure white background, "
            "no shading, no gradients, no texture, lots of white negative space. "
            "Only the key object of the idea is vivid red; everything else is black line art."
        ),
    },
    "classic-dark": {
        "name": "Classic · Dark",
        "note": "White stick figure on a pitch-black canvas, glowing accent colour.",
        "intro": "A minimalist stick figure illustration.",
        "hero": "a stick figure with a hollow circular head with no face, a single straight line for a body and thin straight white line limbs",
        "people": "Every person is a simple white stick figure with a hollow round head and thin uniform line limbs, no realistic hair or clothing, no realistic hands; figures are drawn large and close.",
        "look": (
            "Bold clean white vector linework of uniform medium weight on a perfectly flat pitch black background, "
            "no shading, no gradients, no texture, lots of black negative space. "
            "Only the key object of the idea glows electric cyan; everything else is white line art."
        ),
    },
    "studio-tech": {
        "name": "Studio Tech",
        "note": "A character in a red beanie, bright white studio, floating cyan glass UI.",
        "intro": "A frame from a clean minimalist 2D explainer animation.",
        "hero": "a flat 2D stick figure with a round white head with two black dot eyes, a bright red smooth knit beanie with no pom-pom, a yellow t-shirt, black shorts and thin black stick arms and legs",
        "people": "Every person is a flat 2D stick figure with a round white head, two black dot eyes and thin black stick limbs, never a realistic human: no realistic hair, no noses, no realistic hands; figures are drawn large and close.",
        "look": (
            "Setting: a bright white high-key studio with a subtle light gray perspective grid on the floor and clean white negative space, "
            "with a few sleek glowing cyan and blue translucent glass panels and holographic icons floating in the air. "
            "Clean flat vector style with crisp outlines, vibrant colours, strictly minimalist, no clutter."
        ),
    },
    "cinematic": {
        "name": "Cinematic Story",
        "note": "A character in a red beanie, in rich full-colour scenes with cinematic light.",
        "intro": "A frame from a 2D animated short film.",
        "hero": "a flat 2D stick figure with a round white head with two black dot eyes, a bright red smooth knit beanie with no pom-pom, a yellow t-shirt, black shorts and thin black stick arms and legs",
        "people": "Every person is a flat hand-drawn 2D stick figure with a round white head, two black dot eyes and thin black stick limbs, never a realistic human and never 3D: no realistic hair, no noses, no realistic hands; figures are drawn large and close.",
        "look": (
            "The flat stick figures stand in a rich, full-colour painted 2D environment with cinematic composition, "
            "soft volumetric light, gentle depth of field and an emotional, story-driven mood. Crisp clean outlines."
        ),
    },
}

# Beyond stickmen: fully illustrated styles. Their characters are real people and creatures, so
# the director describes hair, clothes and faces instead of stick figures. The prompts describe the
# look in plain words (no studio or artist names).
STYLES.update({
    "storybook": {
        "name": "Storybook",
        "note": "A children's picture book: soft watercolour and pencil on cream paper.",
        "kind": "illustrated",
        "intro": "A children's picture book illustration.",
        "people": "Rounded, friendly characters with simple dot eyes; the main character is large in the frame.",
        "look": (
            "Soft watercolor washes and delicate colored-pencil linework on textured cream paper, "
            "gentle pastel palette, cozy and heartwarming, clear simple composition."
        ),
    },
    "comic": {
        "name": "Comic book",
        "note": "Bold ink lines, flat colours and dramatic angles, like a graphic novel.",
        "kind": "illustrated",
        "intro": "One single comic-book-style illustration that fills the entire frame edge to edge (not a comic page).",
        "people": "Expressive characters with consistent faces and outfits.",
        "look": (
            "Bold confident black ink outlines, flat vivid colors with subtle halftone shading, "
            "dramatic camera angle and strong lighting, dynamic energy. Exactly one scene in one image: no multiple panels, "
            "no panel grid, no gutters, no borders, no white margins, no frames, no speech bubbles."
        ),
    },
})

NO_TEXT = "No text, no letters, no numbers, no words, no captions, no speech bubbles, no watermark."


def kind(style: str) -> str:
    """"stick" for the stickman styles, "illustrated" for fully drawn characters."""
    return STYLES.get(style, {}).get("kind", "stick")


# Output size and the size the image model draws at (multiples of 64, about one megapixel).
FORMATS = {
    "9:16": {"name": "Vertical 9:16", "out": (1080, 1920), "draw": (768, 1344)},
    "16:9": {"name": "Wide 16:9", "out": (1920, 1080), "draw": (1344, 768)},
}

DURATIONS = [30, 60, 90, 120, 180]

# The languages a video can be narrated in. Scenes and looks stay in English (the image model reads
# English best); everything spoken or shown as text is in the video's language.
LANGUAGES = {
    "en": {"name": "English", "words_per_second": 2.9},
    "hi": {"name": "हिन्दी · Hindi", "words_per_second": 2.4},
}

# Kokoro's voices, best first within each language (Kokoro's own quality grades: Heart A, Bella A-,
# the rest B–C). The narrator picks one; the cast of a story is given the others.
VOICES = {
    "af_heart": {"name": "Heart · warm American female", "lang": "en", "gender": "female"},
    "af_bella": {"name": "Bella · bright American female", "lang": "en", "gender": "female"},
    "bf_emma": {"name": "Emma · British female", "lang": "en", "gender": "female"},
    "am_michael": {"name": "Michael · American male", "lang": "en", "gender": "male"},
    "am_fenrir": {"name": "Fenrir · deep American male", "lang": "en", "gender": "male"},
    "bm_george": {"name": "George · British male", "lang": "en", "gender": "male"},
    "af_nicole": {"name": "Nicole · soft American female", "lang": "en", "gender": "female"},
    "af_sky": {"name": "Sky · young American female", "lang": "en", "gender": "female"},
    "bf_isabella": {"name": "Isabella · British female", "lang": "en", "gender": "female"},
    "am_puck": {"name": "Puck · lively American male", "lang": "en", "gender": "male"},
    "bm_fable": {"name": "Fable · British male", "lang": "en", "gender": "male"},
    "bm_lewis": {"name": "Lewis · older British male", "lang": "en", "gender": "male"},
    "hf_alpha": {"name": "Alpha · Hindi female", "lang": "hi", "gender": "female"},
    "hf_beta": {"name": "Beta · Hindi female", "lang": "hi", "gender": "female"},
    "hm_omega": {"name": "Omega · Hindi male", "lang": "hi", "gender": "male"},
    "hm_psi": {"name": "Psi · Hindi male", "lang": "hi", "gender": "male"},
}

# Who tells the story: one narrator (as before), a narrator with the characters speaking their own
# lines, or the characters alone.
TELLING = {
    "narrator": "One narrator",
    "mixed": "Narrator + character voices",
    "characters": "Characters only",
}

NARRATOR = "Narrator"

MUSIC = {
    "curious": "Curious",
    "calm": "Calm",
    "uplifting": "Uplifting",
    "off": "None",
}

# focus_*: a close look at one part of the frame (left, centre or right), so a conversation can cut
# between the people in one drawing as each of them speaks.
CAMERA_MOVES = ["push_in", "pull_out", "pan_left", "pan_right", "rise", "still", "focus_left", "focus_center", "focus_right"]


def options() -> dict:
    from .planner import MODES

    return {
        "modes": [{"id": k, "name": m["name"], "note": m["note"], "defaults": m["defaults"]} for k, m in MODES.items()],
        "styles": [{"id": "auto", "name": "Auto", "note": "The director picks the look that fits what you wrote."}]
        + [{"id": k, "name": v["name"], "note": v["note"]} for k, v in STYLES.items()],
        "formats": [{"id": k, "name": v["name"]} for k, v in FORMATS.items()],
        "durations": DURATIONS,
        "voices": [{"id": k, "name": v["name"], "language": v["lang"], "gender": v["gender"]} for k, v in VOICES.items()],
        "languages": [{"id": k, "name": v["name"]} for k, v in LANGUAGES.items()],
        "telling": [{"id": k, "name": v} for k, v in TELLING.items()],
        "music": [{"id": k, "name": v} for k, v in MUSIC.items()],
    }


def default_voice(language: str) -> str:
    return next(k for k, v in VOICES.items() if v["lang"] == language)


def cast_voices(characters: list[dict], narrator: str, language: str) -> list[dict]:
    """Gives each character a voice of their gender in the video's language, each different from
    the narrator's and from one another while there are enough to go round. A voice the user
    already chose (and that suits the language) is kept."""
    used = {narrator} | {c["voice"] for c in characters if c.get("voice") in VOICES and VOICES[c["voice"]]["lang"] == language}
    out = []
    for c in characters:
        c = dict(c)
        if c.get("voice") not in VOICES or VOICES[c["voice"]]["lang"] != language:
            gender = c.get("gender") if c.get("gender") in ("female", "male") else "female"
            pool = [k for k, v in VOICES.items() if v["lang"] == language and v["gender"] == gender]
            fresh = [k for k in pool if k not in used]
            c["voice"] = (fresh or [k for k in pool if k != narrator] or pool)[0]
            used.add(c["voice"])
        out.append(c)
    return out


def cast_in(scene: str, characters: list[dict]) -> list[dict]:
    """The plan's characters who appear in this scene (named in it)."""
    return [c for c in characters if re.search(rf"\b{re.escape(c['name'])}\b", scene, re.I)]


# The start of a stickman look ("a small stick figure with ..."), so only what sets the
# character apart is kept: the style decides how a stick figure is drawn.
_STICK_LEAD = re.compile(r"^(an?|the)?\s*(\w+\s+){0,2}?stick ?(figure|man|woman)s?\s*(,|with|wearing|who has|in)?\s*", re.I)
_HEADWEAR = re.compile(r"\b(hat|cap|beanie|helmet|hood|crown|bandana|headband)\b", re.I)
_A_FIGURE = re.compile(r"\b(stick figures?|figures?|person|people|man|woman|boy|girl|child|he|she)\b", re.I)


def looks_in(scene: str, characters: list[dict], changes: dict | None) -> dict:
    """The changed looks (a haircut, new clothes) of the characters in this scene."""
    names = {c["name"] for c in cast_in(scene, characters)}
    return {k: v for k, v in (changes or {}).items() if k in names and v}


def image_prompt(style: str, scene: str, characters: list[dict] = (), changes: dict | None = None) -> str:
    """The style's fixed look around the scene, plus how each character in it looks, so they
    stay recognisable from shot to shot (the image model sees one shot at a time).

    In the stickman styles the main character (listed first) always gets the style's locked look;
    the others are stick figures set apart by an accessory or colour, never realistic people."""
    s = STYLES[style]
    characters = list(characters)
    cast = cast_in(scene, characters)
    who = []
    if kind(style) == "stick":
        main = characters[0] if characters else None
        for c in cast:
            mark = _STICK_LEAD.sub("", c["look"].strip()).rstrip(".")
            if c is main:
                # The locked look, plus what sets them apart unless it's headwear that would fight
                # the style's own (the beanie).
                extra = f", with {mark}" if mark and not _HEADWEAR.search(mark) and "hero" in s and "beanie" in s["hero"] else ""
                who.append(f"{c['name']} is {s['hero']}{extra}.")
            else:
                who.append(f"{c['name']} is another stick figure drawn the same way, set apart only by {mark}." if mark
                           else f"{c['name']} is another stick figure drawn the same way.")
        if not cast and _A_FIGURE.search(scene):
            who.append(f"The main figure is {s['hero']}.")
    else:
        who = [f"{c['name']} is {c['look'].rstrip('.')}." for c in cast]
    # A look that changed earlier in the story holds from then on (the image model can't know).
    who += [f"{name} now has a changed look: {look}." for name, look in looks_in(scene, characters, changes).items()]
    scene = scene.strip()
    if scene and scene[-1] not in ".!?":
        scene += "."
    return " ".join(p for p in [s["intro"], scene, *who, s["people"], s["look"], NO_TEXT] if p)


def speech_lang(voice: str) -> str:
    """The language code Kokoro's phonemizer reads the voice's text in."""
    if VOICES.get(voice, {}).get("lang") == "hi":
        return "hi"
    return "en-gb" if voice.startswith("b") else "en-us"
