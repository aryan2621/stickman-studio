import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Clapperboard, Cloud, CloudOff, PanelLeftClose, PanelLeftOpen, Plus, Settings2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, fileUrl, onCoreEvent, type CloudNotice, type DownloadState, type JobEvent, type Options, type ProjectSummary, type Status } from './lib/api';
import { Button, IconButton, Spinner, cx, useMediaQuery } from './components/ui';
import { SetupView } from './views/SetupView';
import { NewVideoView } from './views/NewVideoView';
import { ProjectView } from './views/ProjectView';
import { SettingsDialog } from './views/SettingsDialog';

type Screen = { kind: 'new' } | { kind: 'project'; id: string };

export function App() {
    const [status, setStatus] = useState<Status | null>(null);
    const [options, setOptions] = useState<Options | null>(null);
    const [projects, setProjects] = useState<ProjectSummary[]>([]);
    const [screen, setScreen] = useState<Screen>({ kind: 'new' });
    const [job, setJob] = useState<JobEvent | null>(null);
    const [download, setDownload] = useState<DownloadState>({});
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [startError, setStartError] = useState<string | null>(null);
    // The cloud fell back to this Mac during the current job.
    const [cloudNotice, setCloudNotice] = useState<CloudNotice | null>(null);
    // Bumped whenever the core reports a change to a project, so its view reloads.
    const [projectVersion, setProjectVersion] = useState(0);
    const screenRef = useRef(screen);
    screenRef.current = screen;
    // Narrow windows get a slim rail of thumbnails; the full list slides out over the page.
    const wide = useMediaQuery('(min-width: 1100px)');
    const [drawerOpen, setDrawerOpen] = useState(false);
    useEffect(() => {
        if (wide) setDrawerOpen(false);
    }, [wide]);

    const refreshStatus = useCallback(async () => {
        const next = await api.status();
        setStatus(next);
        return next;
    }, []);

    const refreshProjects = useCallback(async () => {
        setProjects(await api.listProjects());
    }, []);

    useEffect(() => {
        Promise.all([refreshStatus(), api.options().then(setOptions), api.listProjects()])
            .then(([status, , list]) => {
                setProjects(list);
                // A video left half-made last time (the app quit or crashed): offer to carry on.
                const unfinished = status.job ? [] : list.filter((p) => p.unfinished);
                if (unfinished.length) {
                    const first = unfinished[0];
                    toast.info(unfinished.length === 1 ? `“${first.title}” wasn’t finished` : `${unfinished.length} videos weren’t finished`, {
                        description: `${first.drawn} of ${first.shots} shots are already drawn. Open it and press Resume to carry on from there.`,
                        action: { label: 'Open', onClick: () => setScreen({ kind: 'project', id: first.id }) },
                        duration: 15000,
                    });
                }
            })
            .catch((e) => setStartError(String(e)));
    }, [refreshStatus]);

    useEffect(() => {
        const unlisten = onCoreEvent((event, data) => {
            if (event === 'job') {
                const e = data as JobEvent;
                if (e.stage === 'idle') {
                    setJob(null);
                    setCloudNotice(null);
                    refreshStatus();
                    refreshProjects();
                    setProjectVersion((v) => v + 1);
                } else if (e.stage === 'shot') {
                    setProjectVersion((v) => v + 1);
                } else {
                    setJob(e);
                }
            } else if (event === 'notice') {
                const notice = data as CloudNotice;
                setCloudNotice(notice);
                refreshStatus();
                toast.warning(`Cloudflare couldn’t do the ${notice.what}`, {
                    description: notice.justThisOne
                        ? `${capitalise(notice.reason)}. That one is being made on this Mac; the rest stay on Cloudflare.`
                        : `${capitalise(notice.reason)}. Continuing on this Mac instead, which is slower.`,
                    duration: 12000,
                });
            } else if (event === 'download') {
                setDownload(data as DownloadState);
            } else if (event === 'exited') {
                setJob(null);
                toast.error('The engine stopped unexpectedly. It restarts on the next action.');
            }
        });
        return () => {
            unlisten.then((f) => f());
        };
    }, [refreshProjects, refreshStatus]);

    const openProject = (id: string) => setScreen({ kind: 'project', id });

    if (startError) {
        return (
            <div className='flex h-full items-center justify-center p-10 text-center'>
                <div className='max-w-md space-y-2'>
                    <h1 className='font-serif text-xl'>Stickman Studio couldn't start its engine</h1>
                    <p className='selectable text-sm text-muted'>{startError}</p>
                </div>
            </div>
        );
    }
    if (!status || !options) {
        return (
            <div className='flex h-full items-center justify-center gap-3 text-muted'>
                <Spinner /> Starting…
            </div>
        );
    }

    const busyProject = job?.project ?? null;
    const sidebar: SidebarProps = {
        projects,
        screen,
        busyProject,
        status,
        onNew: () => {
            setScreen({ kind: 'new' });
            setDrawerOpen(false);
        },
        onOpen: (id: string) => {
            openProject(id);
            setDrawerOpen(false);
        },
        onSettings: () => setSettingsOpen(true),
    };

    return (
        <div className='flex h-full'>
            {wide ? (
                <Sidebar {...sidebar} />
            ) : (
                <>
                    <Rail {...sidebar} onExpand={() => setDrawerOpen(true)} />
                    {drawerOpen && (
                        <div className='fixed inset-0 z-40 flex' onPointerDown={(e) => e.target === e.currentTarget && setDrawerOpen(false)}>
                            <div className='absolute inset-0 bg-black/40' onPointerDown={() => setDrawerOpen(false)} />
                            <div className='relative flex h-full shadow-panel'>
                                <Sidebar {...sidebar} onClose={() => setDrawerOpen(false)} />
                            </div>
                        </div>
                    )}
                </>
            )}

            {/* A size container: each screen lays out for the room the main area has, not the window. */}
            <main className='@container relative min-w-0 flex-1 overflow-hidden'>
                <div className='drag absolute inset-x-0 top-0 z-10 h-12' />
                {!status.ready ? (
                    <SetupView status={status} download={download} onDone={refreshStatus} />
                ) : screen.kind === 'new' ? (
                    <NewVideoView
                        options={options}
                        job={job}
                        cloudConnected={status.cloud.connected}
                        onCreated={(id) => {
                            refreshProjects();
                            openProject(id);
                        }}
                    />
                ) : (
                    <ProjectView
                        key={screen.id}
                        id={screen.id}
                        version={projectVersion}
                        options={options}
                        job={job}
                        cloudNotice={cloudNotice}
                        cloudConnected={status.cloud.connected}
                        onChanged={refreshProjects}
                        onDeleted={() => {
                            refreshProjects();
                            setScreen({ kind: 'new' });
                        }}
                    />
                )}
            </main>

            {settingsOpen && (
                <SettingsDialog
                    status={status}
                    download={download}
                    onRefresh={refreshStatus}
                    onClose={() => {
                        setSettingsOpen(false);
                        refreshStatus();
                    }}
                />
            )}
        </div>
    );
}

type SidebarProps = {
    projects: ProjectSummary[];
    screen: Screen;
    busyProject: string | null;
    status: Status;
    onNew: () => void;
    onOpen: (id: string) => void;
    onSettings: () => void;
};

/** A video's small picture, shaped like the video (tall or wide). */
function Thumb({ p, size = 'md' }: { p: ProjectSummary; size?: 'md' | 'sm' }) {
    const tall = p.settings.ratio === '9:16';
    const box = size === 'md' ? (tall ? 'h-12 w-[27px]' : 'h-[27px] w-12') : tall ? 'h-10 w-[23px]' : 'h-[23px] w-10';
    return (
        <div className={cx('shrink-0 overflow-hidden rounded-md bg-panel-2', box)}>
            {p.thumbnail && <img src={fileUrl(p.thumbnail, p.updatedAt)} className='h-full w-full object-cover' alt='' />}
        </div>
    );
}

/** The full sidebar: the app's name, New video, every video with its state, and Settings. */
function Sidebar({ projects, screen, busyProject, status, onNew, onOpen, onSettings, onClose }: SidebarProps & { onClose?: () => void }) {
    return (
        <aside className='flex h-full w-64 shrink-0 flex-col border-r border-line bg-panel'>
            <div className='drag flex h-12 shrink-0 items-center justify-end px-2'>
                {onClose && (
                    <IconButton label='Hide the list' size='icon-sm' onClick={onClose} className='no-drag'>
                        <PanelLeftClose className='h-4 w-4' />
                    </IconButton>
                )}
            </div>
            <div className='px-4 pb-3'>
                <div className='flex items-center gap-2 font-serif text-lg'>
                    <Clapperboard className='h-5 w-5 text-accent' /> Stickman Studio
                </div>
                <p className='mt-0.5 text-xs text-subtle'>Story in, stickman video out. All on this Mac.</p>
            </div>
            <div className='px-3 pb-3'>
                <Button variant={screen.kind === 'new' ? 'primary' : 'secondary'} className='w-full' onClick={onNew}>
                    <Plus className='h-4 w-4' /> New video
                </Button>
            </div>
            <div className='min-h-0 flex-1 space-y-1 overflow-y-auto px-2 pb-3'>
                {projects.length === 0 && <p className='px-3 py-6 text-center text-xs text-subtle'>Your videos will appear here.</p>}
                {projects.map((p) => {
                    const active = screen.kind === 'project' && screen.id === p.id;
                    return (
                        <button
                            key={p.id}
                            onClick={() => onOpen(p.id)}
                            className={cx('flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors', active ? 'bg-raised' : 'hover:bg-panel-2')}
                        >
                            <Thumb p={p} />
                            <div className='min-w-0 flex-1'>
                                <div className='truncate text-sm text-fg'>{p.title}</div>
                                <div className='flex items-center gap-1.5 truncate text-[11px] text-subtle'>
                                    {busyProject === p.id ? (
                                        <>
                                            <Spinner className='h-2.5 w-2.5' /> Working…
                                        </>
                                    ) : p.unfinished ? (
                                        <span className='truncate text-warning-fg'>
                                            Unfinished · {p.drawn} of {p.shots} drawn
                                        </span>
                                    ) : (
                                        <>
                                            {p.settings.ratio} · {p.settings.duration}s{p.hasVideo ? ' · ready' : ' · plan'}
                                        </>
                                    )}
                                </div>
                            </div>
                        </button>
                    );
                })}
            </div>
            <div className='flex items-center justify-between gap-2 border-t border-line px-3 py-2'>
                <CloudPill status={status} onClick={onSettings} />
                <IconButton label='Settings' size='icon-sm' onClick={onSettings}>
                    <Settings2 className='h-4 w-4' />
                </IconButton>
            </div>
        </aside>
    );
}

/** The sidebar on a narrow window: New video, each video's thumbnail (its title on hover), Settings. */
function Rail({ projects, screen, busyProject, status, onNew, onOpen, onSettings, onExpand }: SidebarProps & { onExpand: () => void }) {
    const cloudProblem = status.cloud.connected && status.cloud.problem && Date.now() / 1000 - status.cloud.problem.at < 6 * 3600;
    return (
        <aside className='flex h-full w-[76px] shrink-0 flex-col items-center border-r border-line bg-panel'>
            {/* Room for the window's traffic lights. */}
            <div className='drag h-12 w-full shrink-0' />
            <div className='flex flex-col items-center gap-2 pb-3'>
                <IconButton label='Show the list of videos' size='icon-sm' onClick={onExpand}>
                    <PanelLeftOpen className='h-4 w-4' />
                </IconButton>
                <IconButton label='New video' variant={screen.kind === 'new' ? 'primary' : 'secondary'} onClick={onNew}>
                    <Plus className='h-4 w-4' />
                </IconButton>
            </div>
            <div className='flex min-h-0 w-full flex-1 flex-col items-center gap-1.5 overflow-y-auto px-2 pb-3'>
                {projects.map((p) => {
                    const active = screen.kind === 'project' && screen.id === p.id;
                    return (
                        <button
                            key={p.id}
                            onClick={() => onOpen(p.id)}
                            title={p.unfinished ? `${p.title} (unfinished: ${p.drawn} of ${p.shots} drawn)` : p.title}
                            aria-label={p.title}
                            className={cx(
                                'relative flex h-14 w-14 shrink-0 items-center justify-center rounded-lg transition-colors',
                                active ? 'bg-raised ring-2 ring-accent/60' : 'hover:bg-panel-2'
                            )}
                        >
                            <Thumb p={p} />
                            {busyProject === p.id && (
                                <span className='absolute inset-0 flex items-center justify-center rounded-lg bg-black/40 text-white'>
                                    <Spinner className='h-3.5 w-3.5' />
                                </span>
                            )}
                            {p.unfinished && busyProject !== p.id && <span className='absolute top-1 right-1 h-2 w-2 rounded-full bg-warning' />}
                        </button>
                    );
                })}
            </div>
            <div className='flex flex-col items-center gap-1 border-t border-line py-2'>
                <IconButton label={status.cloud.connected ? (cloudProblem ? 'Cloud unavailable' : 'Cloudflare connected') : `On this Mac · ${status.ramGb} GB`} size='icon-sm' onClick={onSettings}>
                    {status.cloud.connected ? (
                        cloudProblem ? <AlertTriangle className='h-4 w-4 text-warning-fg' /> : <Cloud className='h-4 w-4 text-success-fg' />
                    ) : (
                        <CloudOff className='h-4 w-4' />
                    )}
                </IconButton>
                <IconButton label='Settings' size='icon-sm' onClick={onSettings}>
                    <Settings2 className='h-4 w-4' />
                </IconButton>
            </div>
        </aside>
    );
}

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** Where the heavy work runs: the cloud (on, or with a problem) or this Mac. */
function CloudPill({ status, onClick }: { status: Status; onClick: () => void }) {
    const cloud = status.cloud;
    const on = cloud.connected;
    const recentProblem = cloud.problem && Date.now() / 1000 - cloud.problem.at < 6 * 3600 ? cloud.problem : null;
    let icon, label, tone, title;
    if (on && recentProblem) {
        icon = <AlertTriangle className='h-3.5 w-3.5' />;
        label = 'Cloud unavailable';
        tone = 'text-warning-fg';
        title = `${capitalise(recentProblem.reason)}. Working on this Mac until it’s back.`;
    } else if (on) {
        icon = <Cloud className='h-3.5 w-3.5' />;
        label = 'Cloudflare connected';
        tone = 'text-success-fg';
        title = 'Each video chooses where it’s made: this Mac or Cloudflare.';
    } else {
        icon = <CloudOff className='h-3.5 w-3.5' />;
        label = `On this Mac · ${status.ramGb} GB`;
        tone = 'text-subtle';
        title = 'Everything runs on this Mac. You can connect Cloudflare in Settings to draw faster.';
    }
    return (
        <button onClick={onClick} title={title} className={cx('flex items-center gap-1.5 rounded-md px-1.5 py-1 text-[11px] hover:bg-panel-2', tone)}>
            {icon}
            {label}
        </button>
    );
}
