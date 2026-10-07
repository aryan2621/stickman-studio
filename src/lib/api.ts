import { convertFileSrc, invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

// Shapes returned by the Python core (core/stickman_core). Keep in sync with ipc.py / projects.py.

export type Ratio = '9:16' | '16:9';
export type Captions = 'subtitles' | 'keywords' | 'off';
export type Camera = 'push_in' | 'pull_out' | 'pan_left' | 'pan_right' | 'rise' | 'still' | 'focus_left' | 'focus_center' | 'focus_right';
/** Who tells the story: one narrator, a narrator with the characters speaking, or only the characters. */
export type Telling = 'narrator' | 'mixed' | 'characters';
/** The speaker of narration lines. */
export const NARRATOR = 'Narrator';
/** The part of the video a shot belongs to, named by the director ("Blackout", "The lesson"). */
export type Stage = string;

export interface VideoSettings {
    ratio: Ratio;
    duration: number;
    style: string;
    voice: string;
    speed: number;
    captions: Captions;
    /** The user's own music file (overrides `musicMood`). */
    music?: string | null;
    musicMood?: string;
    /** Whooshes on the transitions. */
    sfx?: boolean;
    /** Where the plan and the drawings are made. */
    engine?: Engine;
    /** The template the plan follows ("auto": none, the source decides). */
    mode?: string;
    /** The language everything spoken and captioned is in ("en", "hi"). */
    language?: string;
    telling?: Telling;
}

export type Engine = 'local' | 'cloud';

export interface Character {
    name: string;
    look: string;
    gender?: 'female' | 'male';
    /** The voice their lines are read in. */
    voice?: string;
}

export interface Shot {
    stage: Stage;
    /** Who says the line: "Narrator" or a character's name. */
    speaker: string;
    /** Shows the previous shot's drawing; only the camera moves (a conversation in one picture). */
    samePicture: boolean;
    narration: string;
    scene: string;
    camera: Camera;
    caption: string;
    image: string | null;
    imageStale: boolean;
    audioStale: boolean;
    seconds: number | null;
}

export interface Project {
    id: string;
    createdAt: string;
    updatedAt: string;
    story: string;
    settings: VideoSettings;
    folder: string;
    title: string;
    message: string;
    characters: Character[];
    shots: Shot[];
    video: string | null;
    /** A sketch preview, when it's newer than the finished video. */
    preview: string | null;
    videoSeconds: number | null;
    videoStale: boolean;
    music: string | null;
    drawn: number;
    unfinished: boolean;
}

export interface ProjectSummary {
    id: string;
    title: string;
    updatedAt: string;
    settings: VideoSettings;
    thumbnail: string | null;
    hasVideo: boolean;
    /** Some shots drawn but the video never finished (the app quit, or it was cancelled). */
    unfinished: boolean;
    drawn: number;
    shots: number;
}

export interface Options {
    styles: { id: string; name: string; note: string }[];
    formats: { id: Ratio; name: string }[];
    durations: number[];
    voices: { id: string; name: string; language: string; gender: 'female' | 'male' }[];
    languages: { id: string; name: string }[];
    telling: { id: Telling; name: string }[];
    music: { id: string; name: string }[];
    modes: { id: string; name: string; note: string; defaults: Partial<Pick<VideoSettings, 'musicMood' | 'captions' | 'speed'>> }[];
}

export interface ModelChoice {
    id: string;
    kind: 'story' | 'image';
    name: string;
    note: string;
    minRamGb: number;
    sizeMb: number;
    downloaded: boolean;
    active: boolean;
}

export interface Memory {
    availableGb: number;
    swapGb: number;
    neededGb: number;
    low: boolean;
    topApps: { name: string; gb: number }[];
}

export interface DownloadState {
    file?: string;
    done?: number;
    total?: number;
    index?: number;
    count?: number;
}

export interface Job {
    project: string | null;
    kind: string;
    message?: string;
    done?: number;
    total?: number;
}

export interface CloudStatus {
    accountId: string;
    connected: boolean;
    /** The last time the cloud couldn't do the work this session, and why. */
    problem: { what: 'images' | 'story'; reason: string; at: number } | null;
}

/** The cloud couldn't do something, so this Mac did it instead. */
export interface CloudNotice {
    kind: 'cloud-fallback';
    /** "drawing", "planning", or "drawing of shot 6" when only that shot was refused. */
    what: string;
    reason: string;
    /** Only this request fell back; the rest of the job still uses the cloud. */
    justThisOne?: boolean;
}

export interface Status {
    ramGb: number;
    settings: { story: string; image: string };
    ready: boolean;
    missing: { id: string; sizeMb: number }[];
    choices: ModelChoice[];
    downloading: DownloadState;
    job: Job | null;
    cloud: CloudStatus;
}

/** A progress message from the core while a job runs. */
export interface JobEvent {
    project: string | null;
    stage: 'plan' | 'voice' | 'images' | 'shot' | 'render' | 'idle';
    message?: string;
    done?: number;
    total?: number;
    shot?: number;
    image?: string;
    seconds?: number;
}

export interface ShotEdit {
    /** Index of the shot this came from in the saved plan (keeps its drawing and voice), if any. */
    from?: number;
    narration: string;
    scene: string;
    camera: Camera;
    caption: string;
    speaker?: string;
    samePicture?: boolean;
}

function call<T>(method: string, params?: Record<string, unknown>): Promise<T> {
    return invoke<T>('core', { method, params: params ?? {} });
}

export const api = {
    options: () => call<Options>('options'),
    status: () => call<Status>('status'),
    download: () => call<void>('download'),
    cancelDownload: () => call<void>('cancel_download'),
    setSettings: (changes: Partial<Status['settings']>) => call<Status>('set_settings', changes),
    deleteModel: (id: string) => call<void>('delete_model', { id }),
    listProjects: () => call<ProjectSummary[]>('list_projects'),
    getProject: (id: string) => call<Project>('get_project', { id }),
    createProject: (story: string, settings: Partial<VideoSettings>) => call<Project>('create_project', { story, settings }),
    revisePlan: (id: string, notes: string, duration?: number) => call<Project>('revise_plan', { id, notes, duration }),
    updateProject: (
        id: string,
        changes: { title?: string; shots?: ShotEdit[]; settings?: Partial<VideoSettings>; characters?: { name: string; voice: string }[] }
    ) =>
        call<Project>('update_project', { id, changes }),
    produce: (id: string) => call<Project>('produce', { id }),
    preview: (id: string) => call<Project>('preview', { id }),
    memory: () => call<Memory>('memory'),
    musicSample: (mood: string) => call<string>('music_sample', { mood }),
    cloudConnect: (accountId: string, token: string) => call<CloudStatus>('cloud_connect', { accountId, token }),
    cloudDisconnect: () => call<void>('cloud_disconnect'),
    redrawShot: (id: string, index: number) => call<Project>('redraw_shot', { id, index }),
    importMusic: (id: string, path: string) => call<Project>('import_music', { id, path }),
    exportVideo: (id: string, path: string) => call<string>('export_video', { id, path }),
    shareStart: (id: string) => call<{ url: string; qr: string; expiresAt: number; network: string; vpn: boolean }>('share_start', { id }),
    shareStop: () => call<void>('share_stop'),
    removeMusic: (id: string) => call<Project>('remove_music', { id }),
    deleteProject: (id: string) => call<void>('delete_project', { id }),
    cancel: () => call<void>('cancel'),
    logsDir: () => invoke<string>('logs_dir'),
};

/** A macOS notification, only when the app isn't in front (otherwise the toast is enough). */
export async function notifyIfAway(title: string, body: string) {
    if (document.hasFocus()) return;
    try {
        const { isPermissionGranted, requestPermission, sendNotification } = await import('@tauri-apps/plugin-notification');
        let granted = await isPermissionGranted();
        if (!granted) granted = (await requestPermission()) === 'granted';
        if (granted) sendNotification({ title, body });
    } catch {
        // Notifications are a nicety; never let them break the flow.
    }
}

export function onCoreEvent(handler: (event: string, data: unknown) => void) {
    return listen<{ event: string; data: unknown }>('core-event', (e) => handler(e.payload.event, e.payload.data));
}

/** A local file as a URL the webview can show. `version` busts the cache after a file changes. */
export function fileUrl(path: string, version?: string | number) {
    const url = convertFileSrc(path);
    return version === undefined ? url : `${url}?v=${encodeURIComponent(String(version))}`;
}

/** Older videos used five fixed parts; newer ones name their own. */
const OLD_STAGE_NAMES: Record<string, string> = {
    hook: 'Hook',
    disrupt: 'Twist',
    secret: 'Secret',
    truth: 'Truth',
    elevate: 'Payoff',
};

export const stageName = (stage: Stage) => OLD_STAGE_NAMES[stage] ?? stage;

export const CAMERA_NAMES: Record<Camera, string> = {
    push_in: 'Push in',
    pull_out: 'Pull out',
    pan_left: 'Pan left',
    pan_right: 'Pan right',
    rise: 'Rise',
    still: 'Still',
    focus_left: 'Focus left',
    focus_center: 'Focus centre',
    focus_right: 'Focus right',
};

export const TELLING_NOTES: Record<Telling, string> = {
    narrator: 'One narrator reads every line, dialogue included.',
    mixed: 'A narrator tells the story; the characters speak their own lines in their own voices.',
    characters: 'No narrator: the characters tell the story themselves, in their own voices.',
};

/** How long a text takes to narrate (seconds), at the narrator's normal pace. */
export const readingSeconds = (text: string) => text.split(/\s+/).filter(Boolean).length / 2.9;

/** The offered length closest to `seconds`. */
export const nearestLength = (seconds: number, lengths: number[]) =>
    lengths.reduce((best, d) => (Math.abs(d - seconds) < Math.abs(best - seconds) ? d : best), lengths[0]);

export const lengthLabel = (d: number) => (d < 60 || d % 60 ? `${d}s` : `${d / 60} min`);

export function formatGb(mb: number) {
    return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${mb} MB`;
}

export function formatDuration(seconds: number) {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s ? `${m}m ${s}s` : `${m} min`;
}
