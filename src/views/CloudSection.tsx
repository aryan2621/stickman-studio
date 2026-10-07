import { useState } from 'react';
import { AlertTriangle, Cloud, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import { openUrl } from '@tauri-apps/plugin-opener';
import { api, type CloudStatus } from '../lib/api';
import { Badge, Button, Spinner } from '../components/ui';

const TOKENS_PAGE = 'https://dash.cloudflare.com/profile/api-tokens';

/** Connect Cloudflare Workers AI, and choose what runs there. */
export function CloudSection({ cloud, onChange }: { cloud: CloudStatus; onChange: () => void }) {
    const [account, setAccount] = useState(cloud.accountId);
    const [token, setToken] = useState('');
    const [connecting, setConnecting] = useState(false);

    const connect = async () => {
        setConnecting(true);
        try {
            await api.cloudConnect(account, token);
            setToken('');
            toast.success('Cloudflare connected. Choose “Cloudflare” under “Make it on” for a video.');
            onChange();
        } catch (e) {
            toast.error(`Couldn’t connect: ${String(e)}`);
        } finally {
            setConnecting(false);
        }
    };


    return (
        <div className='space-y-3'>
            <div>
                <h3 className='flex items-center gap-2 text-sm font-medium text-fg'>
                    <Cloud className='h-4 w-4 text-accent' /> Cloud (Cloudflare Workers AI)
                    {cloud.connected ? <Badge tone='success'>Connected</Badge> : <Badge>Off</Badge>}
                </h3>
                <p className='mt-1 text-xs leading-relaxed text-subtle'>
                    A faster place to make videos: shots in seconds instead of about a minute, plans by a much larger model. The
                    drawings come out simpler than on this Mac. The free tier covers roughly 5–8 one-minute videos a day. Your story and scene descriptions are sent to
                    Cloudflare. If the cloud can’t do something (the day’s free allowance is used up, or you’re offline), this Mac takes
                    over and you’ll see a warning.
                </p>
            </div>

            {cloud.connected ? (
                <div className='space-y-2 rounded-xl border border-line p-3'>
                    <p className='text-xs text-muted'>
                        Each video chooses where it’s made: pick <span className='font-medium text-fg'>This Mac</span> or{' '}
                        <span className='font-medium text-fg'>Cloudflare</span> under “Make it on” when you start a video, or in a video’s side panel.
                    </p>
                    {cloud.problem && (
                        <div className='flex gap-2 rounded-md bg-warning-soft p-2 text-xs text-warning-fg'>
                            <AlertTriangle className='mt-0.5 h-3.5 w-3.5 shrink-0' />
                            <span>Last time, the cloud couldn’t help: {cloud.problem.reason}. This Mac did the work instead.</span>
                        </div>
                    )}
                    <div className='flex items-center justify-between pt-1 text-[11px] text-subtle'>
                        <span className='font-mono'>Account {cloud.accountId.slice(0, 8)}…</span>
                        <Button
                            variant='ghost'
                            size='sm'
                            onClick={async () => {
                                await api.cloudDisconnect();
                                onChange();
                            }}
                        >
                            Disconnect
                        </Button>
                    </div>
                </div>
            ) : (
                <div className='space-y-2 rounded-xl border border-line p-3'>
                    <ol className='list-decimal space-y-1 pl-4 text-xs text-muted'>
                        <li>Sign up or log in at Cloudflare (free).</li>
                        <li>
                            Create an API token with the <span className='font-medium text-fg'>Workers AI</span> template.{' '}
                            <button className='inline-flex items-center gap-0.5 text-accent hover:underline' onClick={() => openUrl(TOKENS_PAGE)}>
                                Open the tokens page <ExternalLink className='h-3 w-3' />
                            </button>
                        </li>
                        <li>
                            Find your Account ID: in the Cloudflare dashboard it’s the 32-character code in the address bar
                            (dash.cloudflare.com/<span className='font-mono text-fg'>your-account-id</span>/…), or click ⋯ next to your account name and
                            choose Copy account ID.
                        </li>
                        <li>Paste the Account ID and the token below.</li>
                    </ol>
                    <input
                        value={account}
                        onChange={(e) => setAccount(e.target.value)}
                        placeholder='Account ID'
                        spellCheck={false}
                        className='h-9 w-full rounded-lg border border-line bg-panel-2 px-3 font-mono text-xs outline-none focus:border-accent'
                    />
                    <input
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        placeholder='API token'
                        type='password'
                        spellCheck={false}
                        className='h-9 w-full rounded-lg border border-line bg-panel-2 px-3 font-mono text-xs outline-none focus:border-accent'
                    />
                    <div className='flex items-center justify-between'>
                        <span className='text-[11px] text-subtle'>The token is kept in your Mac’s Keychain.</span>
                        <Button variant='primary' size='sm' disabled={connecting || !account.trim() || !token.trim()} onClick={connect}>
                            {connecting ? <Spinner className='h-3.5 w-3.5' /> : <Cloud className='h-3.5 w-3.5' />} Connect
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}
