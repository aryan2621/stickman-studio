import { useEffect, useState, type ReactNode } from 'react';
import { ArrowRight, Monitor, Smartphone } from 'lucide-react';
import { toast } from 'sonner';
import { api, lengthLabel, nearestLength, readingSeconds, TELLING_NOTES, type Captions, type Engine, type JobEvent, type Options, type Ratio, type Telling } from '../lib/api';
import { EnginePicker, engineNote } from '../components/EnginePicker';
import { Button, Field, Segmented, Select, Spinner, cx } from '../components/ui';
import { StyleSwatch } from '../components/StyleSwatch';
import { MusicPreview } from '../components/MusicPreview';

const EXAMPLES = [
    'A stickman finds a tiny seed in a cracked city street and waters it every day, until the whole street turns green.',
    'Gravity bends space and time so strongly around a black hole that even light cannot escape.',
    'Why the most successful people schedule time to do nothing.',
    'The compound effect: tiny 1% improvements every day add up to something huge in a year.',
];

const DRAFT_KEY = 'new-video-draft';

function loadDraft() {
    try {
        return JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}');
    } catch {
        return {};
    }
}

/** Step 1: the story and the format. The plan comes next, for review before anything is drawn. */
export function NewVideoView({
    options,
    job,
    cloudConnected,
    onCreated,
}: {
    options: Options;
    job: JobEvent | null;
    cloudConnected: boolean;
    onCreated: (id: string) => void;
}) {
    const draft = loadDraft();
    const [story, setStory] = useState<string>(draft.story ?? '');
    const [ratio, setRatio] = useState<Ratio>(draft.ratio ?? '9:16');
    const [duration, setDuration] = useState<number>(draft.duration ?? 60);
    const [style, setStyle] = useState<string>(draft.style ?? options.styles[0].id);
    const [language, setLanguage] = useState<string>(options.languages.some((l) => l.id === draft.language) ? draft.language : 'en');
    const voicesFor = (lang: string) => options.voices.filter((v) => v.language === lang);
    const [voice, setVoice] = useState<string>(voicesFor(language).some((v) => v.id === draft.voice) ? draft.voice : voicesFor(language)[0].id);
    const [telling, setTelling] = useState<Telling>(options.telling.some((t) => t.id === draft.telling) ? draft.telling : 'mixed');
    /** The narrator speaks the video's language: a new language brings its first voice. */
    const chooseLanguage = (lang: string) => {
        setLanguage(lang);
        if (!voicesFor(lang).some((v) => v.id === voice)) setVoice(voicesFor(lang)[0].id);
    };
    const [captions, setCaptions] = useState<Captions>(draft.captions === 'both' ? 'subtitles' : (draft.captions ?? 'subtitles'));
    const [musicMood, setMusicMood] = useState<string>(draft.musicMood ?? 'curious');
    const [engine, setEngine] = useState<Engine>(draft.engine === 'cloud' && cloudConnected ? 'cloud' : 'local');
    const [mode, setMode] = useState<string>(options.modes.some((m) => m.id === draft.mode) ? draft.mode : 'auto');
    const [speed, setSpeed] = useState<number>(draft.speed ?? 1);
    const template = options.modes.find((m) => m.id === mode) ?? options.modes[0];
    // The length that would fit the whole text (stories and scripts are told nearly in full).
    const fitsLength = nearestLength(readingSeconds(story), options.durations);

    /** A template brings its suggested music, captions and pace (all still changeable). */
    const chooseMode = (id: string) => {
        setMode(id);
        const defaults = options.modes.find((m) => m.id === id)?.defaults ?? {};
        if (defaults.musicMood) setMusicMood(defaults.musicMood);
        if (defaults.captions) setCaptions(defaults.captions);
        if (defaults.speed) setSpeed(defaults.speed);
    };
    const [working, setWorking] = useState(false);
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        try {
            localStorage.setItem(DRAFT_KEY, JSON.stringify({ story, ratio, duration, style, voice, captions, musicMood, engine, mode, speed, language, telling }));
        } catch {
            // Not saving the draft is fine.
        }
    }, [story, ratio, duration, style, voice, captions, musicMood, engine, mode, speed, language, telling]);

    useEffect(() => {
        if (!working) return;
        const started = Date.now();
        const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
        return () => clearInterval(timer);
    }, [working]);

    const busyElsewhere = !!job && !working;

    const create = async () => {
        setWorking(true);
        setElapsed(0);
        try {
            const project = await api.createProject(story, { ratio, duration, style, voice, captions, musicMood, engine, mode, speed, language, telling });
            setStory('');
            onCreated(project.id);
        } catch (e) {
            if (String(e) !== 'Cancelled') toast.error(String(e));
        } finally {
            setWorking(false);
        }
    };

    return (
        // One column until there's room for two (story beside settings); the action bar stays in view.
        <div className='@container flex h-full flex-col'>
            <div className='min-h-0 flex-1 overflow-y-auto'>
                <div className='mx-auto grid max-w-6xl items-start gap-8 px-5 pt-14 pb-8 @min-[40rem]:px-8 @min-[58rem]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] @min-[58rem]:gap-10 @min-[58rem]:px-10 @min-[58rem]:pt-16'>
                    {/* Left: what the video is about. */}
                    <div className='min-w-0 space-y-6'>
                        <div className='space-y-1'>
                            <h1 className='font-serif text-2xl @min-[40rem]:text-3xl'>What should the video be?</h1>
                            <p className='text-muted'>
                                A story, a script, an idea to explain, a poem, notes, or just a topic. The director shapes the video around what you write, and
                                you review the plan before anything is drawn.
                            </p>
                        </div>

                        <div className='space-y-2'>
                            <textarea
                                value={story}
                                onChange={(e) => setStory(e.target.value)}
                                placeholder='e.g. A short story about a lonely lighthouse keeper, or: why do we procrastinate on the things that matter most?'
                                rows={10}
                                disabled={working}
                                className='w-full resize-y rounded-xl border border-line bg-panel p-4 text-[15px] leading-relaxed text-fg outline-none placeholder:text-subtle focus:border-accent'
                            />
                            {!story && (
                                <div className='flex flex-wrap gap-2'>
                                    {EXAMPLES.map((example) => (
                                        <button key={example} onClick={() => setStory(example)} className='rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-line-strong hover:text-fg'>
                                            {example.length > 60 ? example.slice(0, 58) + '…' : example}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>

                        <Field label='Template' hint={template.note}>
                            <div className='grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2'>
                                {options.modes.map((m) => (
                                    <button
                                        key={m.id}
                                        onClick={() => chooseMode(m.id)}
                                        title={m.note}
                                        className={cx(
                                            'truncate rounded-lg border-2 px-3 py-2 text-left text-sm transition-colors',
                                            mode === m.id ? 'border-accent bg-accent/10 text-fg' : 'border-line text-muted hover:border-line-strong hover:text-fg'
                                        )}
                                    >
                                        {m.name}
                                    </button>
                                ))}
                            </div>
                        </Field>

                    </div>

                    {/* Right (or below): how it looks and sounds, in three small groups. */}
                    <div className='min-w-0 space-y-4'>
                        <Section title='Picture'>
                            <div className='grid gap-3 @min-[27rem]:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]'>
                                <Field label='Format'>
                                    <Segmented
                                        size='sm'
                                        value={ratio}
                                        onChange={setRatio}
                                        options={[
                                            { value: '9:16', label: 'Vertical', icon: <Smartphone className='h-3.5 w-3.5' />, hint: 'Shorts, TikTok, Reels' },
                                            { value: '16:9', label: 'Wide', icon: <Monitor className='h-3.5 w-3.5' />, hint: 'YouTube' },
                                        ]}
                                    />
                                </Field>
                                <Field label='Length'>
                                    <Segmented
                                        size='sm'
                                        value={duration}
                                        onChange={setDuration}
                                        options={options.durations.map((d) => ({ value: d, label: d < 60 || d % 60 ? `${d}s` : `${d / 60}m`, hint: `${d} seconds` }))}
                                    />
                                </Field>
                            </div>
                            {fitsLength > duration * 1.3 && (
                                <div className='flex flex-wrap items-center gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[11px] leading-snug text-warning-fg'>
                                    <span className='min-w-[12rem] flex-1'>
                                        Your text reads in about {lengthLabel(fitsLength)}. At {lengthLabel(duration)} the director will shorten it a lot.
                                    </span>
                                    <Button size='sm' variant='secondary' onClick={() => setDuration(fitsLength)}>
                                        Use {lengthLabel(fitsLength)}
                                    </Button>
                                </div>
                            )}
                            <Field label='Style'>
                                <div className='grid grid-cols-[repeat(auto-fill,minmax(5.5rem,1fr))] gap-2'>
                                    {options.styles.map((s) => (
                                        <button
                                            key={s.id}
                                            onClick={() => setStyle(s.id)}
                                            title={s.note}
                                            className={cx(
                                                'overflow-hidden rounded-lg border-2 bg-panel text-left transition-colors',
                                                style === s.id ? 'border-accent' : 'border-transparent hover:border-line-strong'
                                            )}
                                        >
                                            <StyleSwatch style={s.id} />
                                            <div className={cx('truncate px-1.5 py-1 text-[11px] font-medium', style === s.id ? 'text-fg' : 'text-muted')}>{s.name}</div>
                                        </button>
                                    ))}
                                </div>
                                <p className='text-[11px] leading-snug text-subtle'>{options.styles.find((s) => s.id === style)?.note}</p>
                            </Field>
                        </Section>

                        <Section title='Sound'>
                            <div className='grid gap-3 @min-[24rem]:grid-cols-2'>
                                <Field label='Language'>
                                    <Select value={language} onChange={(e) => chooseLanguage(e.target.value)}>
                                        {options.languages.map((l) => (
                                            <option key={l.id} value={l.id}>
                                                {l.name}
                                            </option>
                                        ))}
                                    </Select>
                                </Field>
                                <Field label='Who tells it'>
                                    <Select value={telling} onChange={(e) => setTelling(e.target.value as Telling)}>
                                        {options.telling.map((t) => (
                                            <option key={t.id} value={t.id}>
                                                {t.name}
                                            </option>
                                        ))}
                                    </Select>
                                </Field>
                                <p className='col-span-full -mt-1 text-[11px] leading-snug text-subtle'>
                                    {TELLING_NOTES[telling]}
                                    {telling !== 'narrator' && ' Each character gets their own voice; you can change them on the plan.'}
                                    {language !== 'en' && ' Scenes stay in English for the image model; everything spoken and captioned is in your language.'}
                                </p>
                                <Field label={telling === 'characters' ? 'Fallback voice' : 'Narrator'}>
                                    <Select value={voice} onChange={(e) => setVoice(e.target.value)}>
                                        {voicesFor(language).map((v) => (
                                            <option key={v.id} value={v.id}>
                                                {v.name}
                                            </option>
                                        ))}
                                    </Select>
                                </Field>
                                <Field label='Pace'>
                                    <Segmented
                                        size='sm'
                                        value={speed}
                                        onChange={setSpeed}
                                        options={[
                                            { value: 0.9, label: 'Calm' },
                                            { value: 1, label: 'Normal' },
                                            { value: 1.1, label: 'Brisk' },
                                        ]}
                                    />
                                </Field>
                                <Field label='Music'>
                                    <div className='flex min-w-0 gap-2'>
                                        <Select value={musicMood} onChange={(e) => setMusicMood(e.target.value)}>
                                            {options.music.map((m) => (
                                                <option key={m.id} value={m.id}>
                                                    {m.name}
                                                </option>
                                            ))}
                                        </Select>
                                        <MusicPreview mood={musicMood} />
                                    </div>
                                </Field>
                                <Field label='Captions'>
                                    <Select value={captions} onChange={(e) => setCaptions(e.target.value as Captions)}>
                                        <option value='subtitles'>Subtitles</option>
                                        <option value='keywords'>Key words</option>
                                        <option value='off'>None</option>
                                    </Select>
                                </Field>
                            </div>
                        </Section>

                        <Section title='Where to make it'>
                            <EnginePicker value={engine} cloudConnected={cloudConnected} onChange={setEngine} disabled={working} />
                            <p className='text-[11px] leading-snug text-subtle'>{engineNote(engine, cloudConnected)}</p>
                        </Section>
                    </div>
                </div>
            </div>

            {/* Always in view, whatever the window's size or how far the settings are scrolled. */}
            <div className='shrink-0 border-t border-line bg-panel/90 backdrop-blur'>
                <div className='mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3 @min-[40rem]:px-8 @min-[58rem]:px-10'>
                    {working ? (
                        <>
                            <Button variant='primary' size='lg' disabled>
                                <Spinner /> Writing the plan… {elapsed}s
                            </Button>
                            <Button variant='ghost' onClick={() => api.cancel()}>
                                Cancel
                            </Button>
                        </>
                    ) : (
                        <Button variant='primary' size='lg' disabled={story.trim().length < 3 || busyElsewhere} onClick={create}>
                            Write the plan · {lengthLabel(duration)} <ArrowRight className='h-4 w-4' />
                        </Button>
                    )}
                    <span className='text-xs text-subtle'>
                        {busyElsewhere ? 'Another video is being made. You can start this one when it’s done.' : engine === 'cloud' && cloudConnected ? 'Usually about 20 seconds.' : 'Usually under a minute.'}
                    </span>
                </div>
            </div>
        </div>
    );
}

/** A titled group of settings in the right column. */
function Section({ title, children }: { title: string; children: ReactNode }) {
    return (
        // Each group lays itself out for the room it has (container queries), not the window's width.
        <section className='@container space-y-3 rounded-2xl border border-line bg-panel p-4'>
            <h2 className='text-[11px] font-semibold tracking-wider text-subtle uppercase'>{title}</h2>
            {children}
        </section>
    );
}
