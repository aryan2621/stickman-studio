import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Smartphone, Wifi, X } from 'lucide-react';
import { api, onCoreEvent } from '../lib/api';
import { IconButton, Modal, Spinner } from '../components/ui';

type State = 'starting' | 'waiting' | 'opened' | 'downloaded' | 'error';

/** "Send to phone": a QR code that opens the video on a phone on the same Wi-Fi. Sharing stops
 *  when this closes. */
export function ShareDialog({ projectId, title, onClose }: { projectId: string; title: string; onClose: () => void }) {
    const [share, setShare] = useState<{ url: string; qr: string; expiresAt: number; network: string; vpn: boolean } | null>(null);
    const [state, setState] = useState<State>('starting');
    const [error, setError] = useState('');
    const [left, setLeft] = useState(0);

    useEffect(() => {
        let alive = true;
        api.shareStart(projectId)
            .then((s) => {
                if (!alive) return api.shareStop();
                setShare(s);
                setState('waiting');
            })
            .catch((e) => {
                setError(String(e));
                setState('error');
            });
        const unlisten = onCoreEvent((event, data) => {
            if (event !== 'share') return;
            const next = (data as { state: 'opened' | 'downloaded' }).state;
            setState((current) => (current === 'downloaded' ? current : next));
        });
        return () => {
            alive = false;
            api.shareStop().catch(() => {});
            unlisten.then((f) => f());
        };
    }, [projectId]);

    useEffect(() => {
        if (!share) return;
        const tick = () => {
            const seconds = Math.max(0, Math.round(share.expiresAt - Date.now() / 1000));
            setLeft(seconds);
            if (seconds === 0) onClose();
        };
        tick();
        const timer = setInterval(tick, 1000);
        return () => clearInterval(timer);
    }, [share, onClose]);

    return (
        <Modal onClose={onClose} className='max-w-sm'>
            <div className='flex items-center justify-between border-b border-line px-5 py-3'>
                <h2 className='flex items-center gap-2 font-serif text-lg'>
                    <Smartphone className='h-4 w-4 text-accent' /> Send to phone
                </h2>
                <IconButton label='Close' size='icon-sm' onClick={onClose}>
                    <X className='h-4 w-4' />
                </IconButton>
            </div>
            <div className='space-y-4 p-5 text-center'>
                {state === 'error' ? (
                    <p className='text-sm text-danger-fg'>{error}</p>
                ) : !share ? (
                    <div className='flex h-64 items-center justify-center text-muted'>
                        <Spinner />
                    </div>
                ) : (
                    <>
                        <div className='mx-auto w-60 overflow-hidden rounded-xl bg-white p-2 [&_svg]:h-auto [&_svg]:w-full' dangerouslySetInnerHTML={{ __html: share.qr }} />
                        <p className='text-sm text-fg'>Scan with your phone’s camera to open “{title}” and download it.</p>
                        <div className='flex items-center justify-center gap-1.5 text-xs text-subtle'>
                            <Wifi className='h-3.5 w-3.5' /> Your phone needs to be on the same Wi-Fi as this Mac ({share.network}).
                        </div>
                        <div className='rounded-lg bg-panel-2 px-3 py-2 text-xs'>
                            {state === 'downloaded' ? (
                                <span className='flex items-center justify-center gap-1.5 text-success-fg'>
                                    <CheckCircle2 className='h-3.5 w-3.5' /> Downloaded to your phone
                                </span>
                            ) : state === 'opened' ? (
                                <span className='text-fg'>Opened on your phone. Tap “Download video” there.</span>
                            ) : (
                                <span className='flex items-center justify-center gap-1.5 text-muted'>
                                    <Spinner className='h-3 w-3' /> Waiting for your phone…
                                </span>
                            )}
                        </div>
                        <p className='selectable font-mono text-[10px] break-all text-subtle'>{share.url}</p>
                        {share.vpn && (
                            <div className='flex gap-2 rounded-lg bg-warning-soft p-2.5 text-left text-[11px] leading-snug text-warning-fg'>
                                <AlertTriangle className='mt-0.5 h-3.5 w-3.5 shrink-0' />
                                <span>A VPN is connected on this Mac. Many VPNs block other devices on your Wi-Fi from reaching it; if your phone can’t open the link, disconnect the VPN while you send.</span>
                            </div>
                        )}
                        {state === 'waiting' && (
                            <details className='text-left text-[11px] leading-snug text-subtle'>
                                <summary className='cursor-default text-center text-muted'>Phone says “can’t be reached”?</summary>
                                <ol className='mt-2 list-decimal space-y-1 pl-4'>
                                    <li>Make sure the phone is on the same Wi-Fi, not mobile data (turn mobile data off to be sure).</li>
                                    <li>
                                        macOS firewall: if asked whether Stickman Studio may accept incoming connections, choose Allow. Otherwise open System
                                        Settings → Network → Firewall → Options, and set Stickman Studio to “Allow incoming connections”.
                                    </li>
                                    <li>Disconnect any VPN on this Mac while sending.</li>
                                    <li>Some office and guest Wi-Fi networks stop devices talking to each other. Use your home Wi-Fi or your phone’s hotspot instead.</li>
                                </ol>
                            </details>
                        )}
                        <p className='text-[11px] text-subtle'>
                            Sent straight from this Mac over your network, nothing is uploaded. The link stops when you close this
                            {left > 0 ? ` (or in ${Math.ceil(left / 60)} min)` : ''}.
                        </p>
                    </>
                )}
            </div>
        </Modal>
    );
}
