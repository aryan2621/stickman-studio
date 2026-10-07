"""The director: turns whatever the user writes into a plan of shots, each with its narration,
scene, camera move and caption.

By default ("Auto") it isn't tied to one kind of video: the source decides the form. A story is
told as a story (in order, its dialogue kept), a ready-made script keeps its words, a bare topic is
explained with a retention-friendly arc (hook → twist → reveal → payoff, from the Stickman Video
Director skill), and anything else follows its own natural shape. The user can instead pick a
template (Story, Inspiration, Explainer, Top list, How-to, Poem / Quote): a fixed, precise
structure for that kind of video, for more predictable results. Each shot is one drawn frame that the renderer
moves with a camera path; the user reviews and edits the plan before anything is drawn.
"""

import re
import sys
import traceback
from difflib import SequenceMatcher

from . import styles
from .servers import Cancelled, Engines

SECONDS_PER_SHOT = 5.5  # long enough for a line to carry a real thought

SYSTEM = """You are the director of short illustrated videos for YouTube Shorts, TikTok, Reels and YouTube.
You turn the user's source into a shot-by-shot plan. Each shot is ONE illustrated frame shown while one line is spoken; a gentle camera move animates it. {figures_rule}

{form_rule}

{telling_rule}

{language_rule}

Narration rules:
- Read together, the shots' narration is ONE flowing voiceover. Vary sentence length; use rhythm. Most shots end on a full stop or a question mark; at most one shot in four lets a sentence run on into the next (ending that line with a comma or a dash).
- Every shot moves things forward; never restate an earlier line in other words.
- Keep the source's names, numbers and facts. Never invent statistics, studies, quotes or facts. If the source is longer than the video, condense it but keep its key moments; if it's very short, you may add a fitting everyday detail or example.
- No stage directions, emojis, hashtags or speaker labels in the narration; it is read aloud exactly as written.

Characters: list each recurring character, the MAIN character first, with a short drawable look that sets them apart ({look_example}) and their gender ("female" or "male"; for an animal or object pick the voice that suits it). Use their exact names in the scenes where they appear. For a topic, list only the main figure ("the narrator figure") or none.

Changes of look: a character's look holds only what never changes. When a character's appearance changes for the rest of the story (a haircut, an injury, new clothes, growing old), set "look_change" on the FIRST shot that shows the new look, as "Name: the new look" (e.g. "Della: her hair cut short and curled"); every later picture of that character keeps it automatically. Otherwise "look_change" is "".

Scene rules (each "scene" is sent to an image model that sees ONLY that one scene and remembers nothing else):
- Write it as one or two flowing sentences in English that start with the shot size and the place: "Wide shot of a foggy canyon edge at dawn: Zeke kneels on the first red plank, hammering a nail, while mist pours over the cliff behind him."
- Describe ONE frozen moment, like a single comic panel: who is there, the one clear action or pose each is doing, the key props, and where each figure is in the frame (left, centre, right, foreground, background). Never a list of short fragments, never "then", never several moments ("rain falls, snow piles, sun beats down" is three pictures, not one).
- Always restate the place and the time and light, since the image model knows nothing else (e.g. "at night, in the pitch-dark city during a storm, rain falling"). When the time or place changes in the source, change it in the scenes.
- Show what the line says, literally and concretely. Turn feelings and ideas into something visible (a pose, a prop, a visual metaphor); never describe something that can't be drawn ("a feeling of warmth", "a rhythm", "the room breathes").
- Frame it close: the main figure is big in the frame. At most three figures, unless the source calls for a crowd. Name every character who is in the picture; never refer to someone only as "he" or "she".
- Never a close-up of only hands, eyes or a face detail; show the whole figure or the object itself.
- Images must contain no text: no words, labels, numbers, signs with writing, screens with writing or speech bubbles; never ask for words to appear.
- Don't describe the drawing style or the characters' looks; both are added automatically.
- {format_rule}

Same picture: when the next line happens in the very same moment and place (a conversation, a reaction), set "same_picture": true on it: it reuses the previous shot's drawing and only the camera moves, which is quicker to make and feels like one continuous scene. Then its scene repeats the previous scene word for word. A conversation between two people starts with a shot that draws both of them (one on the left, one on the right), and each following line of the exchange uses "same_picture": true with the camera on whoever speaks: focus_left or focus_right (focus_center for someone in the middle). Use it for 2-4 lines in a row at most, then draw a new picture.
Example of a conversation: shot 5 {"speaker": "Narrator", "same_picture": false, "scene": "Wide shot of a park bench at sunset: Riya sits on the left, Arjun on the right.", "camera": "still"}; shot 6 {"speaker": "Arjun", "same_picture": true, "camera": "focus_right"}; shot 7 {"speaker": "Riya", "same_picture": true, "camera": "focus_left"}.

Part: a 1-3 word name for the part of the video this shot belongs to (e.g. "Alone", "Blackout", "The climb", "The lesson"; or for a topic "Hook", "The myth", "The truth"). Consecutive shots of the same part share the name; a new part gets a transition.

Camera: push_in (tension, a reveal, emotion), pull_out (the bigger picture), pan_left / pan_right (travel, journeys, comparison), rise (lift, hope, climbing), still (a quiet beat), focus_left / focus_center / focus_right (a close look at the person on that side of the picture, for whoever is speaking or reacting). Choose what fits each moment.

Caption: 1-3 punchy words that sum up the shot for a big on-screen overlay ("The only light", "Nothing escapes"), in the video's language. It must not repeat the narration word for word.

Style: {style_rule}"""

AUTO_FORM = """First decide what the source is, and give it the form it calls for. Never force a structure the source doesn't have, and never change its meaning, its message or its ending.
- A STORY (characters, events, dialogue): tell it as a story, in order, like a storyteller reading aloud ("Zeke lives alone at the top of..."). Keep every key event and turning point. Keep the characters' dialogue word for word (who says it follows the Voices rule). Keep the characters' feelings (afraid, stunned). If the story states a lesson or moral, the final shot says it, close to the source's words. Don't add rhetorical hooks, "what if" questions or calls to comment that the story doesn't have.
- A SCRIPT or text already written to be read out: keep its words as closely as the length allows; only trim and split it into shots.
- A TOPIC, IDEA or NOTES to explain or argue: hook in the very first line (a surprising question or paradox, never "In this video"), then challenge the common assumption, reveal what's really going on, land the insight, and end with a punchy takeaway (a question to the viewer is welcome here).
- Anything else (a poem, a speech, a joke, a list, steps to follow, an announcement): follow its own shape."""

# Templates: a fixed, precise structure for one kind of video. "auto" lets the source decide.
# `defaults` are what the app suggests for the template (the user can change them).
MODES = {
    "auto": {
        "name": "Auto",
        "note": "No fixed template: the director shapes the video around what you write.",
        "form": AUTO_FORM,
        "defaults": {},
    },
    "story": {
        "name": "Story",
        "note": "A tale told in order, with its characters, dialogue and ending.",
        "form": """TEMPLATE: STORY. Tell the source as a story, like a storyteller reading aloud, in this exact shape:
1. Setup (about 15% of the shots): who, where, and their everyday world. Open on the main character, not a question.
2. Trouble (about 20%): what disrupts that world.
3. Journey (about 35%): events in order, each shot one step further; feelings shown in poses.
4. Turning point (about 15%): the key moment; dialogue goes here, word for word (who says it follows the Voices rule).
5. Ending (about 15%): how it resolves, and the lesson or moral as the very last line, close to the source's words if it has one.
If the source is a full story, keep every key event and its dialogue. If it's only an idea for a story, write the story yourself around it. No rhetorical "what if" hooks, no talking to the viewer, no calls to comment.
Use the part names: Setup, Trouble, Journey, Turning point, Ending.""",
        "defaults": {"musicMood": "calm", "captions": "subtitles", "speed": 1.0},
    },
    "inspire": {
        "name": "Inspiration",
        "note": "A motivational piece that builds to a powerful closing line.",
        "form": """TEMPLATE: INSPIRATION. A motivational short that speaks to the viewer as "you", in this exact shape:
1. The struggle (about 20% of the shots): name a feeling the viewer knows ("You've been working so hard, and nothing seems to change.").
2. The reframe (about 25%): the truth that changes how they see it.
3. The proof (about 30%): a vivid example, image or tiny story that makes the truth felt.
4. The rise (about 15%): rising energy; shorter, stronger sentences.
5. The line (about 10%): one unforgettable closing line, then a short call to act ("Start today.").
Keep the source's message and any lines it insists on. Concrete images over clichés; no invented statistics or quotes.
Use the part names: The struggle, The reframe, The proof, The rise, The line.""",
        "defaults": {"musicMood": "uplifting", "captions": "keywords", "speed": 1.0},
    },
    "explainer": {
        "name": "Explainer",
        "note": "Hook, myth, reveal, insight, takeaway: built to keep viewers watching.",
        "form": """TEMPLATE: EXPLAINER. Explain the source's topic in this exact shape (built for retention):
1. Hook (about 10% of the shots): the very first line is a surprising question or paradox. Never "In this video".
2. The myth (about 20%): what most people assume, then shatter it in one sentence.
3. The reveal (about 30%): what's really going on: the hidden mechanism or detail, step by step.
4. The insight (about 25%): the satisfying "aha" that ties it together.
5. Takeaway (about 15%): a punchy closing line, then a question that invites comments.
Never invent statistics, studies or quotes.
Use the part names: Hook, The myth, The reveal, The insight, Takeaway.""",
        "defaults": {"musicMood": "curious", "captions": "subtitles", "speed": 1.0},
    },
    "list": {
        "name": "Top list",
        "note": "A countdown of facts, tips or ideas, building to number one.",
        "form": """TEMPLATE: TOP LIST. A countdown in this exact shape:
1. Intro (1 shot): a hook that says what the list is ("Five habits that quietly change your life.").
2. The items (all but the last shot): count down from the highest number to number one, each item introduced as "Number N:" followed by one vivid explanation; give each item one or two shots. Save the strongest item for number one.
3. Outro (1 shot): a one-line wrap-up or a question to the viewer.
Use the items the source gives; if it only gives a topic, choose well-known, true items. Never invent statistics.
Part names: Intro, then "Number N" for each item's shots, then Outro.""",
        "defaults": {"musicMood": "uplifting", "captions": "keywords", "speed": 1.0},
    },
    "howto": {
        "name": "How-to",
        "note": "Clear steps to do something, in order, with a tip and the result.",
        "form": """TEMPLATE: HOW-TO. Teach the source's task in this exact shape:
1. Goal (1 shot): what the viewer will be able to do, and why it's worth it.
2. Steps (most of the shots): the steps in order, each introduced as "Step N:" with one clear action per step; show the action being done.
3. Tip (1 shot): the most common mistake and how to avoid it.
4. Result (1 shot): what success looks like.
Be precise and practical; keep the source's steps and their order.
Part names: Goal, "Step N" for each step's shots, Tip, Result.""",
        "defaults": {"musicMood": "calm", "captions": "keywords", "speed": 1.0},
    },
    "poem": {
        "name": "Poem / Quote",
        "note": "Your words read as written, a line or two per shot, unhurried.",
        "form": """TEMPLATE: POEM OR QUOTE. Read the source's own words exactly as written, in order: one line or couplet per shot. Don't rewrite, explain or add commentary. If the text is longer than the video, keep the strongest lines in their original order. If the source is only a theme, write a short, simple poem about it.
Scenes: one quiet, symbolic image per line.
Part names: the stanza ("Verse 1", "Verse 2"...) or, for a quote, "The quote".""",
        "defaults": {"musicMood": "calm", "captions": "subtitles", "speed": 0.9},
    },
}

TELLING_RULES = {
    "narrator": 'Voices: one narrator speaks every line; "speaker" is always "Narrator". Characters\' dialogue is quoted by the narrator ("He asks, \'Why?\'").',
    "mixed": (
        'Voices: a narrator tells the story, and the characters speak their own dialogue in their own voices. '
        '"speaker" is "Narrator" for narration, or the character\'s exact name for a line that character says out loud. '
        'A character\'s line is only their words, as they would say them, in the first person, with no quotation marks and no "he said". '
        'Give dialogue its own shots: about half the shots of a story with dialogue can be spoken by its characters. '
        'For a topic with no characters, the narrator speaks every line.'
    ),
    "characters": (
        'Voices: there is NO narrator. The story is told entirely by its characters, in their own voices: what they say to each other, '
        'and what they tell the viewer about what is happening and how they feel, in the first person ("I have been building this bridge for forty years."). '
        '"speaker" is always one of the characters\' exact names, never "Narrator". No quotation marks, no "he said". '
        'For a topic with no story, the main figure speaks to the viewer as "I".'
    ),
}

LANGUAGE_RULES = {
    "en": "Language: write the title, message, narration and captions in English.",
    "hi": (
        "Language: write the title, message, narration and captions in natural, simple, everyday spoken Hindi, in Devanagari script "
        "(as people really speak it: common words, short sentences; English words that Hindi speakers commonly use are fine, written in Devanagari). "
        "Never use Latin letters in them. Write numbers as words. "
        "The scenes, the characters' looks and the part names stay in English, because the image model only reads English."
    ),
}

# The words a numbered item or step starts with, in each language.
ITEM_LABELS = {"en": {"Number": "Number", "Step": "Step"}, "hi": {"Number": "नंबर", "Step": "स्टेप"}}

FORMAT_RULES = {
    "9:16": "The frame is vertical (9:16): stack the action vertically, keep the main figure large and central, use height and depth.",
    "16:9": "The frame is wide (16:9): stage the action across left, centre and right, use side-by-side comparisons and open space.",
}


def shot_count(duration: int) -> int:
    return max(4, round(duration / SECONDS_PER_SHOT))


def _shares(count: int, shares: list[tuple[str, float]]) -> list[str]:
    """Splits `count` shots between named parts by their shares, at least one shot each."""
    counts = [max(1, round(count * share)) for _, share in shares]
    while sum(counts) > count:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < count:
        biggest = max(range(len(shares)), key=lambda i: shares[i][1])
        counts[biggest] += 1
    return [name for (name, _), n in zip(shares, counts) for _ in range(n)]


def _numbered(count: int, first: list[str], last: list[str], label: str, descending: bool, max_items: int) -> list[str]:
    """Intro/outro shots around numbered items; long videos give an item two shots."""
    middle = max(1, count - len(first) - len(last))
    items = min(middle, max_items)
    per = [middle // items + (1 if i < middle % items else 0) for i in range(items)]
    names = []
    for i, n in enumerate(per):
        number = items - i if descending else i + 1
        names += [f"{label} {number}"] * n
    return (first + names + last)[:count] if count >= len(first) + len(last) + 1 else names[:count]


def outline(mode: str, count: int) -> list[str] | None:
    """The exact part of every shot for a template, or None to let the director decide."""
    if mode == "story":
        return _shares(count, [("Setup", .15), ("Trouble", .2), ("Journey", .35), ("Turning point", .15), ("Ending", .15)])
    if mode == "inspire":
        return _shares(count, [("The struggle", .2), ("The reframe", .25), ("The proof", .3), ("The rise", .15), ("The line", .1)])
    if mode == "explainer":
        return _shares(count, [("Hook", .1), ("The myth", .2), ("The reveal", .3), ("The insight", .25), ("Takeaway", .15)])
    if mode == "list":
        return _numbered(count, ["Intro"], ["Outro"], "Number", descending=True, max_items=7)
    if mode == "howto":
        return _numbered(count, ["Goal"], ["Tip", "Result"], "Step", descending=False, max_items=8)
    return None


def _verse_lines(source: str, count: int) -> list[str] | None:
    """For Poem / Quote: the source's own words split into `count` shots (lines kept whole), or
    None when the source is only a theme to write about."""
    text = source.strip()
    if len(text.split()) < 20:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) == 1:  # prose: split at sentence and clause ends (a poem's own lines stay whole)
        lines = [p.strip() for p in re.split(r"(?<=[.!?;:,])\s+", " ".join(lines)) if p.strip()]
    if len(lines) <= count:
        return lines
    # Join neighbouring lines into `count` chunks of similar length.
    total = sum(len(l) for l in lines)
    chunks, current, size = [], [], 0
    for i, line in enumerate(lines):
        current.append(line)
        size += len(line)
        remaining_lines, remaining_chunks = len(lines) - i - 1, count - len(chunks) - 1
        if remaining_chunks > 0 and (size >= total / count or remaining_lines == remaining_chunks):
            chunks.append(" ".join(current))
            current, size = [], 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def _schema(count: int, choose_style: bool) -> dict:
    properties = {
        "title": {"type": "string", "maxLength": 80},
        "message": {"type": "string", "maxLength": 300},
        "characters": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "maxLength": 40},
                    "look": {"type": "string", "maxLength": 200},
                    "gender": {"type": "string", "enum": ["female", "male"]},
                },
                "required": ["name", "look", "gender"],
            },
        },
        "shots": {
            "type": "array",
            "minItems": count,
            "maxItems": count,
            "items": {
                "type": "object",
                "properties": {
                    "part": {"type": "string", "maxLength": 30},
                    "speaker": {"type": "string", "maxLength": 40},
                    "narration": {"type": "string", "maxLength": 400},
                    "same_picture": {"type": "boolean"},
                    "scene": {"type": "string", "maxLength": 600},
                    "camera": {"type": "string", "enum": styles.CAMERA_MOVES},
                    "caption": {"type": "string", "maxLength": 40},
                    "look_change": {"type": "string", "maxLength": 160},
                },
                "required": ["part", "speaker", "narration", "same_picture", "scene", "look_change", "camera", "caption"],
            },
        },
    }
    required = ["title", "message", "characters", "shots"]
    if choose_style:
        properties = {"style": {"type": "string", "enum": list(styles.STYLES)}, **properties}
        required = ["style", *required]
    return {"type": "object", "properties": properties, "required": required}


FIGURES = {
    "stick": (
        "The characters are stick figures; the style decides how they are drawn. A character's look is only one or two simple, "
        "drawable things that set them apart (a colourful accessory, a hat, a scarf, a prop they carry, being small or tall), never "
        "age, realistic hair, faces or full outfits.",
        'e.g. "a small stick figure with a ponytail and a green scarf"',
    ),
    "illustrated": (
        "The characters are fully illustrated people (or animals, creatures): describe their age, hair, clothes and expression, never stick figures.",
        'e.g. "a girl of about ten with a short black bob, a yellow raincoat and red boots, clutching a paper map"',
    ),
    "auto": (
        "Whether the characters are stick figures or fully illustrated people depends on the style you choose: stick figures for the classic, studio-tech and cinematic styles (then a look is only one or two drawable things that set them apart: an accessory, a hat, a scarf, a prop, never age, realistic hair or full outfits); real people with age, hair, clothes and expression for storybook and comic.",
        'e.g. "a girl of about ten with a short black bob and a yellow raincoat", or for a stickman style "a small stick figure with a ponytail"',
    ),
}


def _style_rule(style: str) -> str:
    if style != "auto":
        return f"the user chose \"{styles.STYLES[style]['name']}\", so don't choose one."
    choices = "; ".join(f"\"{k}\": {v['note']}" for k, v in styles.STYLES.items())
    return (
        "choose the visual style that best fits the source's mood and setting, and give it as \"style\". "
        f"Options: {choices}. Night, darkness or a single light suits classic-dark or cinematic; "
        "a warm, magical or gentle children's tale suits storybook; "
        "action, drama or heroes suit comic; a crisp explanation suits classic-light or studio-tech. "
        "When the story depends on how someone looks (their hair, face, clothes or age, or a change in them), "
        "choose storybook or comic, whose characters are real people: stick figures can't show it."
    )


# A sentence that describes the picture rather than saying something to the viewer.
_DESCRIBES_PICTURE = re.compile(r"\b(stick figures?|the (frame|scene|background|camera)|in the frame|close-up)\b", re.I)


def _spoken(narration: str, source: str) -> str:
    """The narration without stage directions: small models sometimes describe the shot in it,
    and the narrator would read that out. (Unless the source itself talks about stick figures.)"""
    text = " ".join(narration.split())
    if re.search(r"stick ?(figure|man)", source, re.I):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(s for s in sentences if not _DESCRIBES_PICTURE.search(s)).strip()


def _speaker(name: str, characters: list[dict]) -> str:
    """The character a line is spoken by (matched loosely), or the narrator."""
    name = " ".join(str(name).split()).strip(" .:\"'")
    for c in characters:
        if name.lower() == c["name"].lower():
            return c["name"]
    for c in characters:  # "Zeke (whispering)", "Old Zeke"
        if re.search(rf"\b{re.escape(c['name'])}\b", name, re.I):
            return c["name"]
    return styles.NARRATOR


def _side(scene: str, name: str, names: list[str]) -> str | None:
    """Where `name` is placed in a scene ("left", "center", "right"), if the scene says so: the
    first side word after the name and before the next character's name."""
    match = re.search(rf"\b{re.escape(name)}\b", scene, re.I)
    if not match:
        return None
    rest = scene[match.end():]
    others = [m.start() for n in names if n != name for m in [re.search(rf"\b{re.escape(n)}\b", rest, re.I)] if m]
    rest = rest[: min(others)] if others else rest
    side = re.search(r"\b(left|right|cent(?:er|re)|middle)\b", rest, re.I)
    if not side:
        return None
    word = side.group(1).lower()
    return "center" if word in ("centre", "center", "middle") else word


_SAME_PICTURE = re.compile(r"^\s*\(?same (picture|scene|frame|shot)\)?\s*[:.,-]?\s*", re.I)
MAX_SHARED = 4  # lines in a row on one drawing before a new picture


def _conversations(shots: list[dict], characters: list[dict]):
    """Small models rarely use "same picture" on their own. A character's line right after a
    picture that shows them (placed left, centre or right) next to someone else becomes a close
    look at them in that same drawing, so a conversation cuts between the people as they talk."""
    names = [c["name"] for c in characters]
    for i, shot in enumerate(shots):
        if i == 0 or shot["samePicture"] or shot["speaker"] == styles.NARRATOR:
            continue
        source = i - 1
        while source > 0 and shots[source]["samePicture"]:
            source -= 1
        if i - source >= MAX_SHARED:
            continue
        picture = shots[source]["scene"]
        side = _side(picture, shot["speaker"], names)
        if side and len(styles.cast_in(picture, characters)) >= 2:
            shot["samePicture"] = True
            shot["camera"] = f"focus_{side}"


SCRIPTS = {"hi": r"[\u0900-\u097F]"}


def _in_language(text: str, language: str) -> bool:
    """Whether most of the letters in `text` are in the language's script."""
    if language not in SCRIPTS:
        return True
    letters = re.findall(r"[^\W\d_]", text)
    return not letters or len(re.findall(SCRIPTS[language], text)) >= len(letters) * 0.6


def _translate(engines: Engines, plan: dict, shots: list[dict], language: str):
    """Small story models often write English when asked for another language. Translating
    finished lines is a far easier task for them, so the lines are translated in one more pass."""
    name = styles.LANGUAGES[language]["name"].split(" · ")[-1]
    numbered = "\n".join(f"{i + 1}. line: {s['narration']} | caption: {s['caption']}" for i, s in enumerate(shots))
    system = (
        f"You translate the script of a short video into natural, simple, everyday spoken {name}, written in "
        f"{'Devanagari script' if language == 'hi' else 'its own script'}, as people really say it. Keep the meaning, the tone "
        "and the names (write the names in that script too). Never use Latin letters. Write numbers as words. "
        "Translate every line, in the same order; captions stay 1-3 punchy words."
    )
    user = f"Title: {plan['title']}\nMessage: {plan['message']}\n\nLines:\n{numbered}"
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 120},
            "message": {"type": "string", "maxLength": 400},
            "lines": {
                "type": "array", "minItems": len(shots), "maxItems": len(shots),
                "items": {"type": "object", "properties": {"line": {"type": "string", "maxLength": 600}, "caption": {"type": "string", "maxLength": 60}},
                          "required": ["line", "caption"]},
            },
        },
        "required": ["title", "message", "lines"],
    }
    answer = _ask(engines, system, user, schema, 0.3)
    for shot, line in zip(shots, answer["lines"]):
        text = " ".join(line["line"].split()).strip(_QUOTES + " ")
        if text and _in_language(text, language):
            shot["narration"] = text
        if line["caption"].strip() and _in_language(line["caption"], language):
            shot["caption"] = line["caption"].strip().strip(_QUOTES)
    for key in ("title", "message"):
        if answer[key].strip() and _in_language(answer[key], language):
            plan[key] = answer[key].strip().strip(_QUOTES)


def _continuity(engines: Engines, plan: dict, source: str):
    """Small models rarely mark a change of look (a haircut, an injury) on their own, and then the
    pictures after it show the old look. One short, focused question finds the changes; the code
    then gives every shot the right look: the "before" until the change, the "after" from then on,
    and the lasting look without the part that changes."""
    names = [c["name"] for c in plan["characters"]]
    shots = plan["shots"]
    numbered = "\n".join(f"{i + 1}. {s['narration']} || {s['scene']}" for i, s in enumerate(shots))
    looks = "\n".join(f"- {c['name']}: {c['look']}" for c in plan["characters"])
    system = ("You check a video plan for continuity. Find each character whose appearance changes for the rest of the story "
              "(a haircut, an injury, new clothes, growing old) in the source: only what you can SEE on their body or clothes. "
              "Something they sell, give away or carry is not a change of look. Most stories have none: then return an empty list.")
    user = (f"Source:\n\"\"\"\n{source.strip()}\n\"\"\"\n\nCharacters and their looks:\n{looks}\n\nShots:\n{numbered}\n\n"
            "For each change give: the character's name; their look WITHOUT the feature that changes (\"lasting\"); that feature "
            "before the change (\"before\", e.g. \"very long wavy brown hair down to her knees\"); after it (\"after\", e.g. "
            "\"brown hair cut short and curled\"); and the first shot whose picture shows the new look (\"from_shot\").")
    schema = {
        "type": "object",
        "properties": {"changes": {"type": "array", "maxItems": 4, "items": {"type": "object", "properties": {
            "name": {"type": "string", "enum": names},
            "lasting": {"type": "string", "maxLength": 200},
            "before": {"type": "string", "maxLength": 160},
            "after": {"type": "string", "maxLength": 160},
            "from_shot": {"type": "integer", "minimum": 1, "maximum": len(shots)},
        }, "required": ["name", "lasting", "before", "after", "from_shot"]}}},
        "required": ["changes"],
    }
    answer = engines.chat_json(system, user, schema, temperature=0.2)
    for change in answer.get("changes", []):
        name = _speaker(change.get("name", ""), plan["characters"])
        before, after = " ".join(change.get("before", "").split()), " ".join(change.get("after", "").split())
        start = int(change.get("from_shot", 0)) - 1
        if name == styles.NARRATOR or not before or not after or not 0 < start < len(shots) or before.lower() == after.lower():
            continue
        # The feature that changes ("hair") is in both descriptions; it mustn't stay in the
        # lasting look, or every picture would carry the old one too.
        feature = (set(_tokens(before)) & set(_tokens(after))) - _PLAIN_WORDS
        if not feature or _AN_ACTION.search(after):
            continue  # "gold watch" -> "sold his watch" is something done, not a look
        for c in plan["characters"]:
            if c["name"] == name:
                lasting = " ".join(change.get("lasting", "").split()) or c["look"]
                kept = [part for part in re.split(r",\s*|\s+(?:with|and|wearing)\s+", lasting)
                        if part.strip() and not set(_tokens(part)) & feature]
                c["look"] = ", ".join(kept) or c["look"]
        for i, shot in enumerate(shots):
            shot["looks"] = {**shot.get("looks", {}), name: before if i < start else after}


# Words that don't name a feature of someone's look.
_PLAIN_WORDS = {"a", "an", "the", "her", "his", "their", "and", "with", "of", "to", "in", "on", "now", "cut", "very", "is", "has", "own"}

# An "after" that tells what someone did rather than how they look.
_AN_ACTION = re.compile(r"\b(sold|sells|gave|gives|given|bought|buys|traded|lent|lost|stole|pawned|gave away|no longer has|without (his|her|their))\b", re.I)

_SPOKEN = re.compile(r"""(?:^|[\s,:—–-])["“'‘]([^"”'’]*?(?:[’'](?:[a-z]{1,2})\b[^"”'’]*?)*)["”'’](?=\s|$|[.,!?])""")


def _give_dialogue_to_speakers(shots: list[dict], characters: list[dict]):
    """The last resort when the narrator still reads a character's words aloud ("She asked,
    'Will you buy my hair?'"): if the picture shows exactly one character, the line becomes theirs,
    in their own voice. The picture already shows what the narration around it said."""
    for shot in shots:
        said = [q.strip() for q in _SPOKEN.findall(shot["narration"]) if len(_tokens(q)) >= 3]
        if not said:  # an opening quote that never closes: the rest of the line is what's said
            tail = re.search(r"""(?:^|[\s,:—–-])["“'‘](.{8,})$""", shot["narration"])
            said = [tail.group(1).strip()] if tail and len(_tokens(tail.group(1))) >= 3 else []
        if shot["speaker"] != styles.NARRATOR:
            # "I curled my hair and whispered, 'Please God...'": a character says only the quoted words.
            if said:
                shot["narration"] = " ".join(said)
            continue
        cast = styles.cast_in(shot["scene"], characters)
        if said and len(cast) == 1:
            shot["speaker"] = cast[0]["name"]
            shot["narration"] = " ".join(said)


def _one_moment(scene: str) -> str:
    """A scene that describes two moments ("Della cries, then turns to the mirror") makes the image
    model draw both (a comic page, or the same person twice): keep the first."""
    first = re.split(r"(?:,|;)?\s+(?:and\s+)?then\s+", scene, maxsplit=1, flags=re.I)[0].rstrip(" ,;")
    return first + "." if len(first.split()) >= 4 and first != scene else scene


def _settle_pictures(shots: list[dict], characters: list[dict]):
    """At most MAX_SHARED lines on one drawing, every shot sharing a picture carries that
    picture's scene word for word (it's what the image was drawn from), and a close look at one
    side of the picture goes where the speaker actually is (not at an empty side)."""
    names = [c["name"] for c in characters]
    run = 0
    for i, shot in enumerate(shots):
        if shot["samePicture"] and i > 0 and run + 1 < MAX_SHARED:
            run += 1
            shot["scene"] = shots[i - 1]["scene"]
        else:
            shot["samePicture"] = False
            run = 0
        if shot["camera"].startswith("focus_"):
            side = _side(shot["scene"], shot["speaker"], names) if shot["speaker"] != styles.NARRATOR else None
            if side:
                shot["camera"] = f"focus_{side}"
            elif shot["camera"] != "focus_center" or len(styles.cast_in(shot["scene"], characters)) >= 2:
                shot["camera"] = "push_in" if not shot["samePicture"] else "still"


_QUOTES = "\"'“”‘’«»"


def _ask(engines: Engines, system: str, user: str, schema: dict, temperature: float) -> dict:
    """The story model's answer, asked a second time (a little cooler) if the first attempt fails:
    a model can run out of room or the engine can stumble once."""
    try:
        return engines.chat_json(system, user, schema, temperature=temperature)
    except Cancelled:
        raise
    except RuntimeError:
        return engines.chat_json(system, user, schema, temperature=max(0.2, temperature - 0.2))


_QUOTED = re.compile(r'["“]([^"”]{2,300})["”]')
_TOKEN = re.compile(r"[\w']+")


def _tokens(text: str) -> list[str]:
    return [t.lower().strip("'") for t in _TOKEN.findall(text.replace("’", "'").replace("‘", "'"))]


def _dialogue(source: str) -> list[str]:
    """The sentences of dialogue in the source (quoted, three words or more), in order. Long
    speeches are split into sentences, since a short video often keeps only part of one."""
    out = []
    for quote in _QUOTED.findall(source):
        for sentence in re.split(r"(?<=[.!?])\s+", quote.strip()):
            if len(_tokens(sentence)) >= 3:
                out.append(sentence)
    return out


def _where_said(quote: str, lines: list[str]) -> int | None:
    """The plan line that keeps most of a quote's words in their order, if one keeps at least
    55% of them (a short video may trim a word or two, but "give it to me" isn't "give me")."""
    words = _tokens(quote)
    best, where = 0.0, None
    for i, line in enumerate(lines):
        blocks = SequenceMatcher(None, words, _tokens(line), autojunk=False).get_matching_blocks()
        kept = sum(b.size for b in blocks)
        share = kept / len(words) if kept >= 3 else 0.0
        if share > best:
            best, where = share, i
    return where if best >= 0.55 else None


def _third_person(line: str, speaker: str, others: list[str] = ()) -> bool:
    """A character's line that is really narration: about them ("She cries.", "Della waits.") or
    telling what someone else does ("Jim came in."; "Jim, darling..." is talking to him)."""
    if re.match(r"\s*(he|she|they|his|her|their)\b", line, re.I) or re.search(rf"\b{re.escape(speaker)}\b", line, re.I):
        return True
    return any(re.match(rf"\s*{re.escape(o)}\b(?!\s*[,!?])", line, re.I) for o in others if o != speaker)


def _review(answer: dict, source: str, telling: str, mode_id: str, language: str, count: int) -> list[str]:
    """What a plan gets wrong that can be checked without reading it like a person: the source's
    dialogue left out or told out of order (which can break a twist), and characters narrating
    themselves in the third person. Each problem is written as an instruction to fix it."""
    problems = []
    shots = answer.get("shots", [])
    lines = [s.get("narration", "") for s in shots]
    names = {c.get("name", "").strip().lower(): c.get("name", "").strip() for c in answer.get("characters", [])}
    if mode_id in ("auto", "story") and language == "en":
        quotes = _dialogue(source)
        if len(quotes) >= 2:
            found = [(q, _where_said(q, lines)) for q in quotes]
            missing = [q for q, at in found if at is None]
            # A long story can't keep every line in a short video, but the key exchanges must stay.
            needed = min(len(quotes), max(3, count // 2))
            if len(quotes) - len(missing) < needed:
                keep = missing[-max(1, needed - (len(quotes) - len(missing))):] if len(missing) > 3 else missing
                problems.append("Keep these lines of dialogue from the source, word for word, each spoken in its own shot: "
                                + " / ".join(f'"{q}"' for q in keep))
            # A phrase the source says twice ("My hair grows so fast") can't tell the order apart.
            echoes = {q for q in quotes for o in quotes if o != q and SequenceMatcher(None, _tokens(q), _tokens(o)).ratio() > 0.5}
            said = [(q, at) for q, at in found if at is not None and q not in echoes]
            # A story's last exchange carries its climax (the twist, the reveal): keep all of it.
            ending = [q for q, at in found[-max(3, -(-len(found) // 3)):] if at is None and q not in echoes]
            if ending and not any(p.startswith("Keep these lines") for p in problems):
                problems.append("Keep the ending's dialogue from the source, word for word, each spoken in its own shot by the "
                                "character who says it, in the source's order: " + " / ".join(f'"{q}"' for q in ending))
            if telling == "mixed" and names:
                read_out = sorted({at + 1 for _, at in said if _speaker(shots[at].get("speaker", ""), [{"name": n} for n in names.values()]) == styles.NARRATOR})
                if read_out:
                    problems.append(f"In shot(s) {', '.join(map(str, read_out))} the narrator reads out a character's dialogue. Give each line of "
                                    "dialogue its own shot, spoken by the character who says it (\"speaker\" is their name, the line is only their "
                                    "words), and let the narrator tell only what happens.")
            for (q1, a1), (q2, a2) in zip(said, said[1:]):
                if a2 < a1:
                    problems.append(f'Tell events in the source\'s order: "{q1}" comes before "{q2}" in the source, but your plan '
                                    f"has them the other way round (shots {a2 + 1} and {a1 + 1}). Keep the story's twist for when the source reveals it.")
                    break
    if telling == "characters":
        for i, shot in enumerate(shots):
            speaker = names.get(str(shot.get("speaker", "")).strip().lower())
            if speaker and _third_person(shot.get("narration", ""), speaker, list(names.values())):
                problems.append(f"Shot {i + 1} is spoken by {speaker} but talks about them in the third person; "
                                f"write it as {speaker}'s own words, with \"I\".")
    return problems


def write_plan(engines: Engines, story: str, settings: dict, previous: dict | None = None, notes: str = "") -> dict:
    duration, ratio, style = settings["duration"], settings["ratio"], settings["style"]
    language = settings.get("language", "en") if settings.get("language") in styles.LANGUAGES else "en"
    telling = settings.get("telling", "narrator") if settings.get("telling") in styles.TELLING else "narrator"
    mode = MODES.get(settings.get("mode", "auto"), MODES["auto"])
    count = shot_count(duration)
    words = round(duration * styles.LANGUAGES[language]["words_per_second"])
    figures, look_example = FIGURES["auto" if style == "auto" else styles.kind(style)]
    system = (SYSTEM.replace("{form_rule}", mode["form"]).replace("{format_rule}", FORMAT_RULES[ratio])
              .replace("{style_rule}", _style_rule(style)).replace("{figures_rule}", figures)
              .replace("{look_example}", look_example).replace("{telling_rule}", TELLING_RULES[telling])
              .replace("{language_rule}", LANGUAGE_RULES[language]))
    user = (
        f"Source:\n\"\"\"\n{story.strip()}\n\"\"\"\n\n"
        f"Make a {duration}-second video with exactly {count} shots and about {words} words of spoken lines in total "
        f"(about {round(words / count)} words per shot, at most {round(words / count * 1.3)}: the video must fit {duration} seconds).\n"
        "Also give a short title (under 8 words; the source's own title if it has one) and its core message in one sentence."
    )
    if language != "en":
        user += f"\nRemember: everything spoken, the title, the message and the captions in {styles.LANGUAGES[language]['name'].split(' · ')[-1]}; scenes and looks in English."
    mode_id = settings.get("mode", "auto")
    verses = _verse_lines(story, count) if mode_id == "poem" else None
    if verses:
        count = len(verses)
        user += "\n\nThe narration of each shot is fixed, the source's own words; copy it exactly and design the scene, camera and caption for it:\n"
        user += "\n".join(f"Shot {i + 1}: \"{v}\"" for i, v in enumerate(verses))
    parts = outline(mode_id, count)
    if parts:
        user += "\n\nFollow this shot plan exactly (shot: part):\n" + "\n".join(f"Shot {i + 1}: {p}" for i, p in enumerate(parts))
        items = len({p for p in parts if re.match(r"(Number|Step) \d+$", p)})
        if mode_id == "list":
            user += f"\nThe list has exactly {items} items; if the intro names how many, it says {items}."
        elif mode_id == "howto":
            user += f"\nThere are exactly {items} steps."
    if previous:
        lines = "\n".join(
            f"{i + 1}. [{s.get('stage', '')}] {s.get('speaker') or styles.NARRATOR}: {s['narration']} || "
            + ("(same picture) " if s.get("samePicture") else "") + s["scene"]
            for i, s in enumerate(previous["shots"])
        )
        user += (
            f"\n\nThis is a revision. The current plan is:\nTitle: {previous['title']}\n{lines}\n\n"
            f"Revise it following these notes, keeping what works:\n{notes.strip() or 'Make it more gripping and more visual.'}"
        )
    if verses:
        user = user.replace(f"exactly {shot_count(duration)} shots", f"exactly {count} shots")
    schema = _schema(count, style == "auto")
    answer = _ask(engines, system, user, schema, 0.7 if not previous else 0.6)
    # Small models tend to write short. One more pass if the voiceover would leave the video
    # noticeably shorter than asked for.
    written = sum(len(_spoken(s["narration"], story).split()) for s in answer["shots"])
    if written < words * 0.8 and not verses:
        lines = "\n".join(f"{i + 1}. {s['narration']}" for i, s in enumerate(answer["shots"]))
        retry = (
            f"{user}\n\nYour draft's spoken lines have only {written} words; they need about {words}. "
            f"Rewrite the plan with fuller spoken lines (about {round(words / count)} words each), using more of the "
            "source's own detail rather than repeating anything. The lines are only the words spoken out "
            "loud: never describe the picture in them; that belongs in the scene. "
            f"Your draft's lines:\n{lines}"
        )
        try:
            longer = engines.chat_json(system, retry, schema, temperature=0.6)
        except RuntimeError:
            longer = None  # keep the first draft; a short video beats no video
        if longer:
            longer_words = sum(len(_spoken(s["narration"], story).split()) for s in longer["shots"])
            if written < longer_words <= words * 1.3:
                answer = longer

    # Check the draft and send it back with what's wrong, up to twice; keep the best version.
    problems = [] if verses else _review(answer, story, telling, mode_id, language, count)
    for _ in range(2):
        if not problems:
            break
        draft = "\n".join(f"{i + 1}. {s.get('speaker', '')}: {s['narration']} || {s['scene']}" for i, s in enumerate(answer["shots"]))
        fix = (f"{user}\n\nYour draft:\n{draft}\n\nIt has these problems. Write the whole plan again, fixing every one of them "
               "and keeping everything else that works:\n- " + "\n- ".join(problems))
        try:
            candidate = _ask(engines, system, fix, schema, 0.5)
        except RuntimeError:
            break
        remaining = _review(candidate, story, telling, mode_id, language, count)
        if len(remaining) < len(problems):
            answer, problems = candidate, remaining

    characters = []
    for c in answer.get("characters", [])[:6]:
        name, look = c.get("name", "").strip(), " ".join(c.get("look", "").split())
        if name and look and not any(name.lower() == k["name"].lower() for k in characters):
            characters.append({"name": name, "look": look, "gender": c.get("gender") if c.get("gender") in ("female", "male") else "female"})
    # Keep the voices the user chose for characters who are still in a revised plan.
    chosen = {c["name"].lower(): c.get("voice") for c in (previous or {}).get("characters", [])}
    for c in characters:
        if chosen.get(c["name"].lower()):
            c["voice"] = chosen[c["name"].lower()]
    narrator = settings.get("voice") or styles.default_voice(language)
    characters = styles.cast_voices(characters, narrator, language)

    labels = ITEM_LABELS[language]
    shots = []
    looks_now: dict[str, str] = {}  # each character's changed look from the shot it changes on
    for i, shot in enumerate(answer["shots"][:count]):
        narration = _spoken(shot["narration"], story) or " ".join(shot["narration"].split())
        speaker = styles.NARRATOR if telling == "narrator" else _speaker(shot.get("speaker", ""), characters)
        if telling == "characters" and speaker == styles.NARRATOR and characters:
            speaker = characters[0]["name"]  # no narrator: the main character tells it
        if speaker != styles.NARRATOR and telling == "mixed" and _third_person(narration, speaker, [c["name"] for c in characters]):
            speaker = styles.NARRATOR  # "She cries." is narration, not something she says
        if speaker != styles.NARRATOR:
            # A character says their own words: no quotation marks or "Zeke:" label to read out.
            narration = re.sub(rf"^\s*{re.escape(speaker)}\s*:\s*", "", narration, flags=re.I).strip(_QUOTES + " ")
        part = " ".join(shot.get("part", "").split())[:24] or "Part"
        if parts:
            part = parts[i]
            # A numbered item or step says its number, on the first shot of that item.
            first_of_item = i == 0 or parts[i - 1] != part
            label = re.match(r"(Number|Step) (\d+)$", part)
            word = labels[label.group(1)] if label else ""
            if label and first_of_item and not re.match(rf"\s*({label.group(1)}|{word})\s+{label.group(2)}\b", narration, re.I):
                narration = f"{word} {label.group(2)}: {narration[0].upper()}{narration[1:]}" if narration else f"{word} {label.group(2)}"
        if verses:
            narration = verses[i]
        scene = _one_moment(" ".join(shot["scene"].split()))
        same = False
        if shots and not verses:
            if _SAME_PICTURE.match(scene):
                same = True
            elif shot.get("same_picture"):
                # Trust the flag only when the scene is (nearly) the previous one: a model that
                # says "same picture" and then describes somewhere new wants a new picture.
                same = SequenceMatcher(None, scene.lower(), shots[-1]["scene"].lower()).ratio() > 0.6
        camera = shot["camera"] if shot["camera"] in styles.CAMERA_MOVES else "push_in"
        change = re.match(r"\s*([^:]{1,40}):\s*(.{3,})", shot.get("look_change") or "")
        if change and not _AN_ACTION.search(change.group(2)):
            who = _speaker(change.group(1), characters)
            if who != styles.NARRATOR:
                looks_now[who] = " ".join(change.group(2).split()).rstrip(".")
        shots.append({
            "stage": part,
            "speaker": speaker,
            "narration": narration,
            "scene": scene,
            "samePicture": same,
            "camera": camera,
            "caption": shot["caption"].strip().strip(_QUOTES),
            "looks": dict(looks_now),
        })
    for shot in shots:  # small models sometimes say a sentence twice in a row
        sentences = re.split(r"(?<=[.!?…।])\s+", shot["narration"])
        shot["narration"] = " ".join(x for k, x in enumerate(sentences) if k == 0 or x.strip().lower() != sentences[k - 1].strip().lower())
    if not verses and telling == "mixed":
        _give_dialogue_to_speakers(shots, characters)
    if not verses:
        _conversations(shots, characters)
    _settle_pictures(shots, characters)
    plan = {"title": answer["title"].strip().strip(_QUOTES), "message": answer["message"].strip(), "characters": characters, "shots": shots}
    if characters and not verses and mode_id in ("auto", "story"):
        try:
            _continuity(engines, plan, story)
        except RuntimeError:
            # The plan still works; only a change of look would be missed.
            print("continuity check failed:\n" + traceback.format_exc(), file=sys.stderr)
    if not verses and sum(not _in_language(s["narration"], language) for s in shots) > len(shots) * 0.2:
        try:
            _translate(engines, plan, shots, language)
        except RuntimeError:
            # Keep what was written (the lines can still be edited by hand), but leave a trace.
            print("translation failed:\n" + traceback.format_exc(), file=sys.stderr)
    # Small models overshoot the length. If the voiceover would run well over, end over-long lines
    # at a sentence boundary (the first sentence always stays), so the video fits what was asked.
    if not verses and sum(len(s["narration"].split()) for s in shots) > words * 1.15:
        limit = round(words / len(shots) * 1.15)
        for shot in shots:
            sentences = re.split(r"(?<=[.!?…।])\s+", shot["narration"])
            kept, total = [], 0
            for sentence in sentences:
                n = len(sentence.split())
                if kept and total + n > limit:
                    break
                kept.append(sentence)
                total += n
            shot["narration"] = " ".join(kept)

    if style == "auto":
        plan["style"] = answer.get("style") if answer.get("style") in styles.STYLES else "cinematic"
        # A story whose characters change how they look needs real people: stick figures can't show it.
        if styles.kind(plan["style"]) == "stick" and any(s.get("looks") for s in shots):
            plan["style"] = "storybook"
    return plan
