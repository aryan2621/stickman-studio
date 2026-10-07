import { useState } from 'react';
import { Check, Download, FileText, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import { revealItemInDir } from '@tauri-apps/plugin-opener';
import { api, formatGb, type DownloadState, type ModelChoice, type Status } from '../lib/api';
import { Badge, Button, IconButton, Modal, ProgressBar, Spinner, cx } from '../components/ui';
import { CloudSection } from './CloudSection';

/** Which story and image models to use, and downloading or deleting them. */
export function SettingsDialog({
    status,
    download,
    onRefresh,
    onClose,
}: {
    status: Status;
    download: DownloadState;
    onRefresh: () => Promise<Status>;
    onClose: () => void;
}) {
    const [downloading, setDownloading] = useState(false);

    const choose = async (choice: ModelChoice) => {
        try {
            await api.setSettings({ [choice.kind]: choice.id });
            const next = await onRefresh();
            if (next.missing.length) {
                setDownloading(true);
                await api.download();
                await onRefresh();
            }
        } catch (e) {
            if (String(e) !== 'Cancelled') toast.error(String(e));
            await onRefresh();
        } finally {
            setDownloading(false);
        }
    };

    const remove = async (choice: ModelChoice) => {
        try {
            await api.deleteModel(choice.id);
            await onRefresh();
        } catch (e) {
            toast.error(String(e));
        }
    };

    const section = (kind: 'story' | 'image', title: string, text: string) => (
        <div className='space-y-2'>
            <div>
                <h3 className='text-sm font-medium text-fg'>{title}</h3>
                <p className='text-xs text-subtle'>{text}</p>
            </div>
            {status.choices
                .filter((c) => c.kind === kind)
                .map((c) => {
                    const tooBig = c.minRamGb > status.ramGb;
                    return (
                        <div key={c.id} className={cx('flex items-center gap-3 rounded-xl border p-3', c.active ? 'border-accent bg-accent/5' : 'border-line')}>
                            <div className='min-w-0 flex-1'>
                                <div className='flex items-center gap-2 text-sm text-fg'>
                                    {c.name}
                                    <span className='text-xs text-subtle'>{formatGb(c.sizeMb)}</span>
                                    {tooBig && <Badge tone='warning'>needs {c.minRamGb} GB memory</Badge>}
                                </div>
                                <p className='text-xs text-muted'>{c.note}</p>
                            </div>
                            {c.active ? (
                                <Badge tone='success'>
                                    <Check className='h-3 w-3' /> In use
                                </Badge>
                            ) : (
                                <>
                                    {c.downloaded && (
                                        <IconButton label='Delete download' size='icon-sm' onClick={() => remove(c)}>
                                            <Trash2 className='h-3.5 w-3.5' />
                                        </IconButton>
                                    )}
                                    <Button size='sm' disabled={downloading || !!status.job} onClick={() => choose(c)}>
                                        {c.downloaded ? (
                                            'Use'
                                        ) : (
                                            <>
                                                <Download className='h-3.5 w-3.5' /> Use
                                            </>
                                        )}
                                    </Button>
                                </>
                            )}
                        </div>
                    );
                })}
        </div>
    );

    const fileProgress = download.total ? (download.done ?? 0) / download.total : 0;

    return (
        <Modal onClose={onClose} dismissable={!downloading} className='max-w-xl'>
            <div className='flex items-center justify-between border-b border-line px-5 py-3'>
                <h2 className='font-serif text-lg'>Settings</h2>
                <IconButton label='Close' size='icon-sm' disabled={downloading} onClick={onClose}>
                    <X className='h-4 w-4' />
                </IconButton>
            </div>
            <div className='max-h-[70vh] space-y-6 overflow-y-auto p-5'>
                {section('story', 'Story AI', 'Writes the director’s plan. Runs only while planning.')}
                {section('image', 'Image AI', 'Draws the shots. Changing it redraws shots the next time a video is updated.')}
                <div className='border-t border-line pt-5'>
                    <CloudSection cloud={status.cloud} onChange={onRefresh} />
                </div>
                {downloading && (
                    <div className='space-y-1.5 rounded-xl bg-panel-2 p-3'>
                        <div className='flex items-center gap-2 text-xs text-muted'>
                            <Spinner className='h-3 w-3' /> Downloading {formatGb(download.done ?? 0)} of {formatGb(download.total ?? 0)}
                        </div>
                        <ProgressBar value={fileProgress} />
                        <Button variant='ghost' size='sm' onClick={() => api.cancelDownload()}>
                            Cancel
                        </Button>
                    </div>
                )}
                <div className='flex items-center justify-between border-t border-line pt-4 text-xs text-subtle'>
                    <span>{status.cloud.connected ? 'Voice and editing always run on this Mac.' : `Everything runs on this Mac (${status.ramGb} GB memory). Nothing is uploaded.`}</span>
                    <Button variant='ghost' size='sm' onClick={async () => revealItemInDir(await api.logsDir())}>
                        <FileText className='h-3.5 w-3.5' /> Logs
                    </Button>
                </div>
            </div>
        </Modal>
    );
}
