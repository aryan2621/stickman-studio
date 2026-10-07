import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowDown, ArrowUp, Clapperboard, Download, QrCode, Eye, FolderOpen, Link2, MemoryStick, Music, Plus, RefreshCw, Trash2, Wand2, X } from 'lucide-react';
import { toast } from 'sonner';
import { open as openDialog, save as saveDialog } from '@tauri-apps/plugin-dialog';
import { downloadDir } from '@tauri-apps/api/path';
import { revealItemInDir } from '@tauri-apps/plugin-opener';
import {
    api,
    CAMERA_NAMES,
    fileUrl,
    formatDuration,
    lengthLabel,
    NARRATOR,
    nearestLength,
    notifyIfAway,
    stageName,
    type Camera,
    type Captions,
    type CloudNotice,
    type JobEvent,
    type Memory,
    type Options,
    type Project,
    type ShotEdit,
    type VideoSettings,
} from '../lib/api';
import { Badge, Button, Field, IconButton, Modal, ProgressBar, Segmented, Select, Spinner, Switch, cx } from '../components/ui';
import { EnginePicker, engineNote } from '../components/EnginePicker';
import { MusicPreview } from '../components/MusicPreview';
import { ShareDialog } from './ShareDialog';

type Draft = ShotEdit & { key: number };

let nextKey = 1;
const toDraft = (project: Project): Draft[] =>
    project.shots.map((s, i) => ({
        key: nextKey++,
        from: i,
        narration: s.narration,
        scene: s.scene,
        camera: s.camera,
        caption: s.caption,
        speaker: s.speaker ?? NARRATOR,
        samePicture: s.samePicture ?? false,
    }));

const SETTING_DEFAULTS: Partial<VideoSettings> = { engine: 'local', musicMood: 'curious', sfx: true, speed: 1 };

/** A video: its plan (editable until you're happy), the drawn shots, and the finished video. */
export function ProjectView({
    id,
    version,
    options,
    job,
    cloudNotice,
    cloudConnected,
    onChanged,
    onDeleted,
}: {
    id: string;
    version: number;
    options: Options;
    job: JobEvent | null;
    cloudNotice: CloudNotice | null;
    cloudConnected: boolean;
    onChanged: () => void;
    onDeleted: () => void;
}) {
    const [project, setProject] = useState<Project | null>(null);
    const [draft, setDraft] = useState<Draft[]>([]);
    const [title, setTitle] = useState('');
    const [revising, setRevising] = useState(false);
    const [confirmDelete, setConfirmDelete] = useState(false);
    const [sharing, setSharing] = useState(false);
    // Low on memory: what to run once the user decides (anyway, or after closing apps).
    const [memoryWarning, setMemoryWarning] = useState<{ memory: Memory; go: () => void } | null>(null);
    const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const saving = useRef<Promise<void> | null>(null);
    const dirty = useRef(false);
    const draftRef = useRef(draft);
    draftRef.current = draft;
    const titleRef = useRef(title);
    titleRef.current = title;

    const busy = job?.project === id;
    const busyOther = !!job && !busy;

    // First load, and a fresh draft whenever the plan is replaced (a revision).
    const load = useCallback(
        async (resetDraft: boolean) => {
            const p = await api.getProject(id);
            setProject(p);
            if (resetDraft) {
                setDraft(toDraft(p));
                setTitle(p.title);
            }
        },
        [id]
    );

    useEffect(() => {
        load(true).catch((e) => toast.error(String(e)));
    }, [load]);

    // The core reports progress (a shot drawn, a job finished): refresh the media, keep the edits.
    useEffect(() => {
        if (version > 0 && !dirty.current) load(false).catch(() => {});
    }, [version, load]);

    const save = useCallback(async () => {
        if (saveTimer.current) {
            clearTimeout(saveTimer.current);
            saveTimer.current = null;
        }
        if (saving.current) await saving.current;
        if (!dirty.current) return;
        dirty.current = false;
        const sent = draftRef.current;
        saving.current = (async () => {
            try {
                const p = await api.updateProject(id, {
                    title: titleRef.current,
                    shots: sent.map(({ from, narration, scene, camera, caption, speaker, samePicture }) => ({
                        from,
                        narration,
                        scene,
                        camera,
                        caption,
                        speaker,
                        samePicture,
                    })),
                });
                setProject(p);
                // The saved order is now the plan's order; later edits refer to these positions.
                setDraft((current) => current.map((d) => {
                    const index = sent.findIndex((s) => s.key === d.key);
                    return { ...d, from: index >= 0 ? index : undefined };
                }));
                onChanged();
            } catch (e) {
                dirty.current = true;
                toast.error(String(e));
            } finally {
                saving.current = null;
            }
        })();
        await saving.current;
    }, [id, onChanged]);

    const scheduleSave = () => {
        dirty.current = true;
        if (saveTimer.current) clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(save, 600);
    };

    // Save pending edits when leaving the video.
    useEffect(() => () => void save(), [save]);

    const edit = (key: number, changes: Partial<ShotEdit>) => {
        setDraft((d) => d.map((s) => (s.key === key ? { ...s, ...changes } : s)));
        scheduleSave();
    };
    const move = (index: number, by: number) => {
        setDraft((d) => {
            const next = [...d];
            const [item] = next.splice(index, 1);
            next.splice(index + by, 0, item);
            return next;
        });
        scheduleSave();
    };
    const remove = (index: number) => {
        // The first shot left has no picture before it to share.
        setDraft((d) => d.filter((_, i) => i !== index).map((s, i) => (i === 0 && s.samePicture ? { ...s, samePicture: false } : s)));
        scheduleSave();
    };
    /** A character's voice is saved straight away; their lines are recorded again next time. */
    const changeVoice = async (name: string, voice: string) => {
        await save();
        try {
            setProject(await api.updateProject(id, { characters: [{ name, voice }] }));
            onChanged();
        } catch (e) {
            toast.error(String(e));
        }
    };
    const add = (index: number) => {
        setDraft((d) => {
            const next = [...d];
            next.splice(index + 1, 0, {
                key: nextKey++,
                narration: 'New line of narration.',
                scene: 'The stick figure…',
                camera: 'push_in',
                caption: '',
                speaker: NARRATOR,
                samePicture: false,
            });
            return next;
        });
        scheduleSave();
    };

    // Side-panel changes wait here until "Apply changes", so the video and the panel never disagree.
    const [pending, setPending] = useState<Partial<VideoSettings>>({});
    const changeSettings = (changes: Partial<VideoSettings>) =>
        setPending((current) => {
            const next = { ...current, ...changes };
            // Changing a setting back to what the video uses isn't a change.
            for (const key of Object.keys(next) as (keyof VideoSettings)[]) {
                if (project && next[key] === (project.settings[key] ?? SETTING_DEFAULTS[key])) delete next[key];
            }
            return next;
        });
    const shown = <K extends keyof VideoSettings>(key: K) => (pending[key] ?? project?.settings[key] ?? SETTING_DEFAULTS[key]) as VideoSettings[K];
    const applyChanges = async () => {
        let updated: Project;
        try {
            updated = await api.updateProject(id, { settings: pending });
            setProject(updated);
            setPending({});
        } catch (e) {
            toast.error(String(e));
            return;
        }
        produce(updated);
    };

    const run = async (work: () => Promise<Project>, done?: string) => {
        await save();
        try {
            const p = await work();
            setProject(p);
            if (done) toast.success(done);
        } catch (e) {
            if (String(e) !== 'Cancelled') toast.error(String(e));
            load(false).catch(() => {});
        }
    };

    const videoTitle = () => titleRef.current || 'Your video';

    /** Drawing needs the image model in memory; warn first if other apps leave too little. */
    const withMemoryCheck = async (go: () => void, current: Project | null = project) => {
        try {
            const memory = await api.memory();
            const inCloud = current?.settings.engine === 'cloud' && cloudConnected;
            if (memory.low && !inCloud) return setMemoryWarning({ memory, go });
        } catch {
            // If the check fails, just go ahead.
        }
        go();
    };

    /** `current`: the video as just saved, when called right after a change. */
    const produce = (current: Project | null = project) => {
        const go = () =>
            run(async () => {
                try {
                    const p = await api.produce(id);
                    notifyIfAway('Your video is ready', `“${videoTitle()}” is ready to watch.`);
                    return p;
                } catch (e) {
                    if (String(e) !== 'Cancelled') notifyIfAway('The video couldn’t be made', String(e));
                    throw e;
                }
            }, 'Your video is ready');
        const needsDrawing = current?.shots.some((s) => s.imageStale) || draft.some((d) => d.from === undefined);
        if (needsDrawing) withMemoryCheck(go, current);
        else go();
    };
    const preview = () => run(() => api.preview(id));
    const redraw = (index: number) => withMemoryCheck(() => run(() => api.redrawShot(id, index)));

    /** Saves a copy of the finished video wherever the user picks (Downloads by default). */
    const download = async () => {
        if (!project) return;
        const name = `${(project.title || 'Stickman video').replace(/[\\/:*?"<>|]/g, '').trim() || 'Stickman video'}.mp4`;
        const target = await saveDialog({ defaultPath: `${await downloadDir()}/${name}`, filters: [{ name: 'Video', extensions: ['mp4'] }] });
        if (!target) return;
        try {
            const saved = await api.exportVideo(id, target);
            toast.success('Video saved', { description: saved, action: { label: 'Show', onClick: () => revealItemInDir(saved) } });
        } catch (e) {
            toast.error(String(e));
        }
    };

    const chooseMusic = async () => {
        const path = await openDialog({ multiple: false, filters: [{ name: 'Audio', extensions: ['mp3', 'm4a', 'aac', 'wav', 'flac', 'ogg'] }] });
        if (typeof path === 'string') {
            try {
                setProject(await api.importMusic(id, path));
            } catch (e) {
                toast.error(String(e));
            }
        }
    };

    if (!project) {
        return (
            <div className='flex h-full items-center justify-center text-muted'>
                <Spinner />
            </div>
        );
    }

    const portrait = project.settings.ratio === '9:16';
    const drawn = project.shots.filter((s) => s.image && !s.imageStale).length;
    const neverMade = !project.video && drawn === 0;
    const style = options.styles.find((s) => s.id === project.settings.style)?.name ?? project.settings.style;
    const totalWords = draft.reduce((n, s) => n + s.narration.split(/\s+/).filter(Boolean).length, 0);
    const drawingShot = busy && job?.stage === 'images' ? job.shot : undefined;
    const language = project.settings.language ?? 'en';
    const voices = options.voices.filter((v) => v.language === language);
    const speakers = [NARRATOR, ...project.characters.map((c) => c.name)];
    const speaks = (name: string) => draft.some((d) => d.speaker === name);
    /** The scene a shot's picture is drawn from: its own, or the one it shares. */
    const pictureScene = (index: number) => {
        let i = index;
        while (i > 0 && draft[i].samePicture) i--;
        return { index: i, scene: draft[i].scene };
    };
    const progress = busy && job?.total ? (job.done ?? 0) / job.total : 0;

    return (
        // Side by side when there's room; otherwise one scrolling page with the video on top.
        <div className='flex h-full flex-col overflow-y-auto @min-[52rem]:flex-row @min-[52rem]:overflow-hidden'>
            {/* The plan */}
            <div className='min-w-0 @min-[52rem]:flex-1 @min-[52rem]:overflow-y-auto'>
                <div className='mx-auto max-w-3xl space-y-5 px-5 pt-8 pb-16 @min-[40rem]:px-8 @min-[52rem]:pt-14'>
                    <div className='space-y-2'>
                        <input
                            value={title}
                            readOnly={busy}
                            onChange={(e) => {
                                setTitle(e.target.value);
                                scheduleSave();
                            }}
                            className='w-full bg-transparent font-serif text-3xl text-fg outline-none'
                            aria-label='Title'
                        />
                        <p className='text-sm text-muted'>{project.message}</p>
                        {project.characters.length > 0 && (
                            <div className='space-y-1 text-xs text-subtle'>
                                <span className='font-medium text-muted'>Cast</span>
                                {project.characters.map((c) => (
                                    <div key={c.name} className='flex items-center gap-2'>
                                        <span className='min-w-0 flex-1 truncate'>
                                            <span className='font-medium text-fg'>{c.name}</span> · {c.look}
                                        </span>
                                        {speaks(c.name) && (
                                            <select
                                                value={c.voice ?? ''}
                                                disabled={busy}
                                                onChange={(e) => changeVoice(c.name, e.target.value)}
                                                className='rounded-md bg-transparent text-xs text-muted outline-none hover:text-fg'
                                                aria-label={`${c.name}'s voice`}
                                            >
                                                {voices.map((v) => (
                                                    <option key={v.id} value={v.id}>
                                                        {v.name}
                                                    </option>
                                                ))}
                                            </select>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className='flex flex-wrap items-center gap-1.5 pt-1'>
                            <Badge>{project.settings.ratio === '9:16' ? 'Vertical 9:16' : 'Wide 16:9'}</Badge>
                            <Badge>{project.settings.duration}s target</Badge>
                            <Badge>{style}</Badge>
                            {language !== 'en' && <Badge>{options.languages.find((l) => l.id === language)?.name ?? language}</Badge>}
                            {project.settings.telling && project.settings.telling !== 'narrator' && (
                                <Badge>{options.telling.find((t) => t.id === project.settings.telling)?.name}</Badge>
                            )}
                            {project.settings.mode && project.settings.mode !== 'auto' && (
                                <Badge>{options.modes.find((m) => m.id === project.settings.mode)?.name ?? project.settings.mode} template</Badge>
                            )}
                            <Badge>
                                {draft.length} shots · {totalWords} words ≈ {formatDuration(totalWords / 3.1 + draft.length * 0.25 + 2.3)}
                            </Badge>
                        </div>
                    </div>

                    {neverMade && (
                        <div className='rounded-xl border border-accent/30 bg-accent/10 p-4 text-sm text-fg'>
                            <span className='font-medium'>This is the director’s plan.</span> Read it through, edit any line, scene or camera move, or ask for a rewrite.
                            When it feels right, approve it and the shots are drawn.
                        </div>
                    )}

                    <div className='space-y-3'>
                        {draft.map((shot, index) => {
                            const saved = shot.from !== undefined ? project.shots[shot.from] : undefined;
                            const isDrawing = drawingShot !== undefined && shot.from === drawingShot;
                            return (
                                <div key={shot.key} className='group relative flex gap-4 rounded-xl border border-line bg-panel p-3'>
                                    <div className={cx('relative shrink-0 overflow-hidden rounded-lg bg-panel-2', portrait ? 'h-[160px] w-[90px]' : 'h-[90px] w-[160px]')}>
                                        {saved?.image ? (
                                            <img src={fileUrl(saved.image, project.updatedAt)} className={cx('h-full w-full object-cover', saved.imageStale && 'opacity-40')} alt='' />
                                        ) : (
                                            <div className={cx('flex h-full w-full items-center justify-center text-xs text-subtle', isDrawing && 'shimmer')}>
                                                {isDrawing ? 'Drawing…' : index + 1}
                                            </div>
                                        )}
                                        {isDrawing && saved?.image && <div className='shimmer absolute inset-0 opacity-70' />}
                                        {saved?.image && !busy && !busyOther && (
                                            <button
                                                onClick={() => redraw(shot.from!)}
                                                title='Draw this shot again'
                                                className='absolute right-1 bottom-1 rounded-md bg-black/60 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100'
                                            >
                                                <RefreshCw className='h-3.5 w-3.5' />
                                            </button>
                                        )}
                                    </div>
                                    <div className='min-w-0 flex-1 space-y-2'>
                                        <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
                                            <span className='font-mono text-xs text-subtle'>{String(index + 1).padStart(2, '0')}</span>
                                            {saved && <Badge tone='accent'>{stageName(saved.stage)}</Badge>}
                                            <select
                                                value={speakers.includes(shot.speaker ?? NARRATOR) ? shot.speaker : NARRATOR}
                                                disabled={busy}
                                                onChange={(e) => edit(shot.key, { speaker: e.target.value })}
                                                className={cx('rounded-md bg-transparent text-xs font-medium outline-none hover:text-fg', shot.speaker && shot.speaker !== NARRATOR ? 'text-accent' : 'text-muted')}
                                                aria-label='Who says this line'
                                            >
                                                {speakers.map((name) => (
                                                    <option key={name} value={name}>
                                                        {name}
                                                    </option>
                                                ))}
                                            </select>
                                            <select
                                                value={shot.camera}
                                                disabled={busy}
                                                onChange={(e) => edit(shot.key, { camera: e.target.value as Camera })}
                                                className='rounded-md bg-transparent text-xs text-muted outline-none hover:text-fg'
                                                aria-label='Camera move'
                                            >
                                                {Object.entries(CAMERA_NAMES).map(([value, name]) => (
                                                    <option key={value} value={value}>
                                                        {name}
                                                    </option>
                                                ))}
                                            </select>
                                            <input
                                                value={shot.caption}
                                                readOnly={busy}
                                                onChange={(e) => edit(shot.key, { caption: e.target.value })}
                                                placeholder='Key words'
                                                className='min-w-[6rem] flex-1 rounded-md bg-transparent px-1 text-xs font-medium text-warning-fg outline-none placeholder:text-subtle focus:bg-panel-2'
                                                aria-label='Key words caption'
                                            />
                                            {/* Floats over the card's corner on hover, so it never takes a line of its own. */}
                                            <div
                                                className={cx(
                                                    'pointer-events-none absolute top-2 right-2 flex rounded-lg border border-line bg-panel/95 opacity-0 shadow-sm transition-opacity',
                                                    !busy && 'group-hover:pointer-events-auto group-hover:opacity-100'
                                                )}
                                            >
                                                <IconButton label='Move up' size='icon-sm' disabled={index === 0} onClick={() => move(index, -1)}>
                                                    <ArrowUp className='h-3.5 w-3.5' />
                                                </IconButton>
                                                <IconButton label='Move down' size='icon-sm' disabled={index === draft.length - 1} onClick={() => move(index, 1)}>
                                                    <ArrowDown className='h-3.5 w-3.5' />
                                                </IconButton>
                                                <IconButton label='Add a shot after this one' size='icon-sm' onClick={() => add(index)}>
                                                    <Plus className='h-3.5 w-3.5' />
                                                </IconButton>
                                                <IconButton label='Remove this shot' size='icon-sm' disabled={draft.length <= 1} onClick={() => remove(index)}>
                                                    <X className='h-3.5 w-3.5' />
                                                </IconButton>
                                            </div>
                                        </div>
                                        <textarea
                                            value={shot.narration}
                                            readOnly={busy}
                                            onChange={(e) => edit(shot.key, { narration: e.target.value })}
                                            rows={2}
                                            className='w-full resize-none rounded-md bg-transparent text-[15px] leading-snug text-fg outline-none focus:bg-panel-2'
                                            aria-label='Narration'
                                        />
                                        {shot.samePicture && index > 0 ? (
                                            <p className='px-0.5 text-xs leading-relaxed text-subtle'>
                                                <Link2 className='mr-1 inline h-3 w-3' />
                                                Same picture as shot {pictureScene(index).index + 1}, the camera moves to a new spot: {pictureScene(index).scene}
                                            </p>
                                        ) : (
                                            <textarea
                                                value={shot.scene}
                                                readOnly={busy}
                                                onChange={(e) => edit(shot.key, { scene: e.target.value })}
                                                rows={2}
                                                className='w-full resize-none rounded-md bg-transparent text-xs leading-relaxed text-muted outline-none focus:bg-panel-2'
                                                aria-label='Scene to draw'
                                            />
                                        )}
                                        {index > 0 && (
                                            <label className='flex items-center gap-1.5 text-[11px] text-subtle'>
                                                <input
                                                    type='checkbox'
                                                    checked={!!shot.samePicture}
                                                    disabled={busy}
                                                    onChange={(e) =>
                                                        edit(shot.key, e.target.checked ? { samePicture: true, scene: pictureScene(index - 1).scene } : { samePicture: false })
                                                    }
                                                />
                                                Same picture as the previous shot (only the camera moves: quicker, and good for conversations)
                                            </label>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    <details className='rounded-xl border border-line bg-panel p-4 text-sm'>
                        <summary className='cursor-default text-muted'>Source story</summary>
                        <p className='selectable mt-2 whitespace-pre-wrap text-muted'>{project.story}</p>
                    </details>
                </div>
            </div>

            {/* The video */}
            <div className='@container/panel order-first w-full shrink-0 border-b border-line bg-panel p-5 pt-14 @min-[52rem]:order-none @min-[52rem]:w-[340px] @min-[52rem]:overflow-y-auto @min-[52rem]:border-b-0 @min-[52rem]:border-l @min-[64rem]:w-[380px]'>
                {/* Two groups (the video and its actions; the settings), side by side when the panel is wide. */}
                <div className='grid min-h-full content-start gap-x-6 gap-y-4 @min-[34rem]/panel:grid-cols-2'>
                    <div className='flex min-w-0 flex-col gap-4'>
                        <div className={cx('mx-auto w-full overflow-hidden rounded-xl bg-stage', portrait ? 'aspect-[9/16] max-h-[52vh] w-auto' : 'aspect-video')}>
                            {project.preview || project.video ? (
                                <div className='relative h-full w-full'>
                                    <video
                                        key={(project.preview ?? project.video) + project.updatedAt}
                                        src={fileUrl((project.preview ?? project.video)!, project.updatedAt)}
                                        controls
                                        className='h-full w-full bg-black object-contain'
                                    />
                                    {project.preview && (
                                        <span className='pointer-events-none absolute top-2 left-2'>
                                            <Badge tone='warning'>Preview: sketches stand in for undrawn shots</Badge>
                                        </span>
                                    )}
                                </div>
                            ) : (
                                <div className='flex h-full w-full flex-col items-center justify-center gap-2 p-6 text-center text-subtle'>
                                    <Clapperboard className='h-8 w-8' />
                                    <span className='text-xs'>The finished video appears here.</span>
                                </div>
                            )}
                        </div>

                        {busy ? (
                            <div className='space-y-2 rounded-xl border border-line bg-panel-2 p-3'>
                                <div className='flex items-center gap-2 text-sm text-fg'>
                                    <Spinner className='h-3.5 w-3.5 text-accent' /> {job?.message ?? 'Working…'}
                                </div>
                                {!!job?.total && <ProgressBar value={progress} />}
                                {cloudNotice && (
                                    <div className='flex gap-2 rounded-md bg-warning-soft p-2 text-[11px] leading-snug text-warning-fg'>
                                        <AlertTriangle className='mt-0.5 h-3.5 w-3.5 shrink-0' />
                                        <span>
                                            Cloudflare couldn’t do the {cloudNotice.what}: {cloudNotice.reason}.{' '}
                                            {cloudNotice.justThisOne ? 'That one is made on this Mac; the rest stay on Cloudflare.' : 'Working on this Mac instead.'}
                                        </span>
                                    </div>
                                )}
                                <Button variant='ghost' size='sm' onClick={() => api.cancel()}>
                                    Cancel
                                </Button>
                            </div>
                        ) : (
                            <div className='space-y-2'>
                                <Button variant='primary' size='lg' className='w-full' disabled={busyOther || (!project.videoStale && !!project.video)} onClick={() => produce()}>
                                    <Wand2 className='h-4 w-4' />
                                    {project.unfinished
                                        ? `Resume (${project.drawn} of ${project.shots.length} shots done)`
                                        : neverMade
                                          ? 'Approve plan & make video'
                                          : project.videoStale
                                            ? 'Update video'
                                            : 'Video is up to date'}
                                </Button>
                                <p className='text-center text-[11px] text-subtle'>
                                    {busyOther
                                        ? 'Another video is being made.'
                                        : project.unfinished
                                          ? 'Carries on where it stopped: the shots already drawn are kept.'
                                          : neverMade
                                          ? `Draws ${draft.filter((d, i) => !(i > 0 && d.samePicture)).length} pictures for ${draft.length} shots, records the voices and edits. Takes a while; you can leave it running.`
                                          : project.videoStale
                                            ? 'The plan or settings changed since this video was made. Only what changed is redone.'
                                            : project.videoSeconds
                                              ? `${formatDuration(project.videoSeconds)} · saved in Movies › Stickman Studio`
                                              : ''}
                                </p>
                            </div>
                        )}

                        {!busy && project.videoStale && (
                            <Button variant='secondary' size='sm' className='w-full' disabled={busyOther} onClick={async () => { await save(); preview(); }}>
                                <Eye className='h-3.5 w-3.5' /> Quick preview with sketches (about a minute)
                            </Button>
                        )}

                        <div className='flex gap-2'>
                            <Button variant='secondary' size='sm' className='flex-1' disabled={busy || busyOther} onClick={() => setRevising(true)}>
                                <Wand2 className='h-3.5 w-3.5' /> Rewrite plan…
                            </Button>
                            <Button variant='secondary' size='sm' className='flex-1' onClick={() => revealItemInDir(project.video ?? project.folder)}>
                                <FolderOpen className='h-3.5 w-3.5' /> Show in Finder
                            </Button>
                        </div>
                        {project.video && (
                            <div className='flex gap-2'>
                                <Button variant='secondary' size='sm' className='flex-1' onClick={download}>
                                    <Download className='h-3.5 w-3.5' /> Download…
                                </Button>
                                <Button variant='secondary' size='sm' className='flex-1' onClick={() => setSharing(true)}>
                                    <QrCode className='h-3.5 w-3.5' /> Send to phone
                                </Button>
                            </div>
                        )}

                    </div>

                    <div className='flex min-w-0 flex-col gap-4'>
                        <div className='space-y-4 border-t border-line pt-4 @min-[34rem]/panel:border-t-0 @min-[34rem]/panel:pt-0'>
                            <div className='text-xs font-medium tracking-wide text-subtle uppercase'>Video settings</div>
                            {Object.keys(pending).length > 0 && (
                                <div className='space-y-2 rounded-xl border border-accent/40 bg-accent/10 p-3'>
                                    <p className='text-xs leading-snug text-fg'>
                                        <span className='font-medium'>
                                            {Object.keys(pending).length === 1 ? '1 change' : `${Object.keys(pending).length} changes`} not in the video yet.
                                        </span>{' '}
                                        {pending.engine
                                            ? `Applying redraws all ${project.shots.length} shots ${pending.engine === 'cloud' ? 'on Cloudflare (a few minutes)' : 'on this Mac (about a minute each)'}.`
                                            : pending.voice || pending.speed
                                              ? 'Applying records the voice again and re-edits the video (about a minute). The drawings are kept.'
                                              : 'Applying re-edits the video (under a minute). The drawings and voice are kept.'}
                                    </p>
                                    <div className='flex gap-2'>
                                        <Button variant='primary' size='sm' className='flex-1' disabled={busy || busyOther} onClick={applyChanges}>
                                            <Wand2 className='h-3.5 w-3.5' /> Apply changes
                                        </Button>
                                        <Button variant='ghost' size='sm' onClick={() => setPending({})}>
                                            Discard
                                        </Button>
                                    </div>
                                </div>
                            )}
                            <Field label='Make it on'>
                                <EnginePicker
                                    value={shown('engine') ?? 'local'}
                                    cloudConnected={cloudConnected}
                                    disabled={busy}
                                    onChange={(engine) => changeSettings({ engine })}
                                />
                                <p className='text-[11px] leading-snug text-subtle'>{engineNote(shown('engine') ?? 'local', cloudConnected)}</p>
                            </Field>
                            <Field label='Narrator'>
                                <Select value={shown('voice')} disabled={busy} onChange={(e) => changeSettings({ voice: e.target.value })}>
                                    {voices.map((v) => (
                                        <option key={v.id} value={v.id}>
                                            {v.name}
                                        </option>
                                    ))}
                                </Select>
                            </Field>
                            <Field label='Speaking pace'>
                                <Segmented
                                    size='sm'
                                    value={shown('speed')}
                                    onChange={(speed) => !busy && changeSettings({ speed })}
                                    options={[
                                        { value: 0.9, label: 'Calm' },
                                        { value: 1, label: 'Normal' },
                                        { value: 1.1, label: 'Brisk' },
                                    ]}
                                />
                            </Field>
                            <Field label='Captions'>
                                <Select value={shown('captions')} disabled={busy} onChange={(e) => changeSettings({ captions: e.target.value as Captions })}>
                                    <option value='subtitles'>Subtitles</option>
                                    <option value='keywords'>Key words</option>
                                    <option value='off'>None</option>
                                </Select>
                            </Field>
                            <Field label='Music' hint='quiet, dips under the voice'>
                                {project.music ? (
                                    <div className='flex items-center gap-2 rounded-lg border border-line bg-panel-2 px-3 py-2 text-xs'>
                                        <Music className='h-3.5 w-3.5 text-accent' />
                                        <span className='min-w-0 flex-1 truncate'>Your file: {project.music.split('/').pop()}</span>
                                        <MusicPreview file={project.music} />
                                        <IconButton label='Remove your music' size='icon-sm' disabled={busy} onClick={async () => setProject(await api.removeMusic(id))}>
                                            <X className='h-3.5 w-3.5' />
                                        </IconButton>
                                    </div>
                                ) : (
                                    <div className='flex gap-2'>
                                        <Select value={shown('musicMood') ?? 'curious'} disabled={busy} onChange={(e) => changeSettings({ musicMood: e.target.value })}>
                                            {options.music.map((m) => (
                                                <option key={m.id} value={m.id}>
                                                    {m.name}
                                                </option>
                                            ))}
                                        </Select>
                                        <MusicPreview mood={shown('musicMood') ?? 'curious'} />
                                        <Button variant='secondary' disabled={busy} onClick={chooseMusic} title='Use your own music file'>
                                            <Music className='h-3.5 w-3.5' /> File…
                                        </Button>
                                    </div>
                                )}
                            </Field>
                            <label className='flex items-center justify-between text-xs text-fg'>
                                Whoosh on scene changes
                                <Switch label='Whoosh on scene changes' checked={shown('sfx') ?? true} disabled={busy} onChange={(sfx) => changeSettings({ sfx })} />
                            </label>
                        </div>

                        <div className='mt-auto pt-4'>
                            <Button variant='ghost' size='sm' className='w-full' disabled={busy} onClick={() => setConfirmDelete(true)}>
                                <Trash2 className='h-3.5 w-3.5' /> Move to Trash
                            </Button>
                        </div>
                    </div>
                </div>
            </div>

            {revising && (
                <ReviseDialog
                    duration={project.settings.duration}
                    durations={options.durations}
                    storyWords={project.story.split(/\s+/).filter(Boolean).length}
                    onClose={() => setRevising(false)}
                    onRevise={async (notes, duration) => {
                        setRevising(false);
                        await save();
                        try {
                            const p = await api.revisePlan(id, notes, duration);
                            setProject(p);
                            setDraft(toDraft(p));
                            setTitle(p.title);
                            onChanged();
                        } catch (e) {
                            if (String(e) !== 'Cancelled') toast.error(String(e));
                        }
                    }}
                />
            )}
            {sharing && <ShareDialog projectId={id} title={project.title} onClose={() => setSharing(false)} />}
            {memoryWarning && (
                <Modal onClose={() => setMemoryWarning(null)} className='max-w-md'>
                    <div className='space-y-4 p-5'>
                        <div className='flex items-start gap-3'>
                            <MemoryStick className='mt-1 h-5 w-5 shrink-0 text-warning-fg' />
                            <div className='space-y-1'>
                                <h2 className='font-serif text-lg'>Your Mac is short on memory</h2>
                                <p className='text-sm text-muted'>
                                    Drawing needs about {memoryWarning.memory.neededGb} GB, and only {memoryWarning.memory.availableGb} GB is free right now
                                    {memoryWarning.memory.swapGb >= 1 ? ` (${memoryWarning.memory.swapGb} GB already swapped to disk)` : ''}. Shots can take several
                                    minutes each instead of about one.
                                </p>
                            </div>
                        </div>
                        {memoryWarning.memory.topApps.length > 0 && (
                            <div className='rounded-lg bg-panel-2 p-3 text-xs'>
                                <div className='mb-1.5 text-subtle'>Using the most memory:</div>
                                {memoryWarning.memory.topApps.map((a) => (
                                    <div key={a.name} className='flex justify-between text-fg'>
                                        <span>{a.name}</span>
                                        <span className='font-mono text-muted'>{a.gb} GB</span>
                                    </div>
                                ))}
                            </div>
                        )}
                        <p className='text-xs text-subtle'>Quit an app or two, then press Check again.</p>
                        <div className='flex justify-end gap-2'>
                            <Button
                                variant='ghost'
                                onClick={() => {
                                    const { go } = memoryWarning;
                                    setMemoryWarning(null);
                                    go();
                                }}
                            >
                                Start anyway
                            </Button>
                            <Button
                                variant='primary'
                                onClick={async () => {
                                    const { go } = memoryWarning;
                                    setMemoryWarning(null);
                                    withMemoryCheck(go);
                                }}
                            >
                                Check again
                            </Button>
                        </div>
                    </div>
                </Modal>
            )}
            {confirmDelete && (
                <Modal onClose={() => setConfirmDelete(false)} className='max-w-sm'>
                    <div className='space-y-4 p-5'>
                        <h2 className='font-serif text-lg'>Move “{project.title}” to the Trash?</h2>
                        <p className='text-sm text-muted'>The plan, the drawings and the video go to the Trash. You can put them back from there.</p>
                        <div className='flex justify-end gap-2'>
                            <Button variant='ghost' onClick={() => setConfirmDelete(false)}>
                                Keep it
                            </Button>
                            <Button
                                variant='danger'
                                onClick={async () => {
                                    try {
                                        await api.deleteProject(id);
                                        onDeleted();
                                    } catch (e) {
                                        toast.error(String(e));
                                    }
                                }}
                            >
                                Move to Trash
                            </Button>
                        </div>
                    </div>
                </Modal>
            )}
        </div>
    );
}

function ReviseDialog({
    duration,
    durations,
    storyWords,
    onClose,
    onRevise,
}: {
    duration: number;
    durations: number[];
    storyWords: number;
    onClose: () => void;
    onRevise: (notes: string, duration: number) => void;
}) {
    const [notes, setNotes] = useState('');
    const [length, setLength] = useState(duration);
    const fits = nearestLength(storyWords / 2.9, durations);
    return (
        <Modal onClose={onClose} className='max-w-lg'>
            <div className='space-y-4 p-5'>
                <div className='space-y-1'>
                    <h2 className='font-serif text-lg'>Rewrite the plan</h2>
                    <p className='text-sm text-muted'>Say what to change, or pick another length. The director rewrites every shot.</p>
                </div>
                <Field
                    label='Length'
                    hint={length !== duration ? 'A new length rewrites the plan from your original text; all shots are drawn again.' : `Your text reads in about ${lengthLabel(fits)}.`}
                >
                    <Segmented size='sm' value={length} onChange={setLength} options={durations.map((d) => ({ value: d, label: lengthLabel(d) }))} />
                </Field>
                <textarea
                    autoFocus
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    rows={4}
                    placeholder='e.g. Make the hook more surprising, use more everyday examples, end on a question about money.'
                    className='w-full resize-none rounded-lg border border-line bg-panel-2 p-3 text-sm outline-none focus:border-accent'
                />
                <div className='flex justify-end gap-2'>
                    <Button variant='ghost' onClick={onClose}>
                        Cancel
                    </Button>
                    <Button variant='primary' onClick={() => onRevise(notes, length)}>
                        <Wand2 className='h-4 w-4' /> Rewrite
                    </Button>
                </div>
            </div>
        </Modal>
    );
}
