import { useState } from 'react';
import { Download, HardDrive, Mic, PenLine, Sparkles } from 'lucide-react';
import { toast } from 'sonner';
import { api, formatGb, type DownloadState, type Status } from '../lib/api';
import { Button, ProgressBar } from '../components/ui';

const PARTS = [
    { icon: PenLine, title: 'A story AI', text: 'writes the director’s plan: narration, scenes and camera moves.' },
    { icon: Sparkles, title: 'An image AI', text: 'draws every shot in the style you pick.' },
    { icon: Mic, title: 'A voice', text: 'reads the narration.' },
];

/** First run: download the models. Everything runs on this Mac afterwards, offline. */
export function SetupView({ status, download, onDone }: { status: Status; download: DownloadState; onDone: () => Promise<Status> }) {
    const [running, setRunning] = useState(false);
    const total = status.missing.reduce((sum, f) => sum + f.sizeMb, 0);

    const start = async () => {
        setRunning(true);
        try {
            await api.download();
            const next = await onDone();
            if (next.ready) toast.success('All set. Write your first story!');
        } catch (e) {
            if (String(e) !== 'Cancelled') toast.error(String(e));
        } finally {
            setRunning(false);
        }
    };

    const fileProgress = download.total ? (download.done ?? 0) / download.total : 0;
    const overall = download.count ? ((download.index ?? 0) + fileProgress) / download.count : 0;

    return (
        <div className='flex h-full items-center justify-center overflow-y-auto p-10'>
            <div className='w-full max-w-lg space-y-6'>
                <div className='space-y-2'>
                    <h1 className='font-serif text-3xl'>One download, then it’s all yours</h1>
                    <p className='text-muted'>
                        Stickman Studio makes videos entirely on this Mac. Nothing you write is uploaded. First it needs three small AI models:
                    </p>
                </div>
                <div className='space-y-3 rounded-xl border border-line bg-panel p-4'>
                    {PARTS.map(({ icon: Icon, title, text }) => (
                        <div key={title} className='flex gap-3'>
                            <Icon className='mt-0.5 h-4 w-4 shrink-0 text-accent' />
                            <p className='text-sm text-muted'>
                                <span className='font-medium text-fg'>{title}</span> {text}
                            </p>
                        </div>
                    ))}
                </div>
                {running ? (
                    <div className='space-y-2'>
                        <ProgressBar value={overall} />
                        <p className='text-xs text-subtle'>
                            {download.count
                                ? `File ${(download.index ?? 0) + 1} of ${download.count}: ${formatGb(download.done ?? 0)} of ${formatGb(download.total ?? 0)}`
                                : 'Starting the download…'}
                        </p>
                        <Button variant='ghost' size='sm' onClick={() => api.cancelDownload()}>
                            Cancel
                        </Button>
                    </div>
                ) : (
                    <div className='flex items-center gap-4'>
                        <Button variant='primary' size='lg' onClick={start}>
                            <Download className='h-4 w-4' /> Download {formatGb(total)}
                        </Button>
                        <span className='flex items-center gap-1.5 text-xs text-subtle'>
                            <HardDrive className='h-3.5 w-3.5' /> You can change the models later in Settings.
                        </span>
                    </div>
                )}
            </div>
        </div>
    );
}
