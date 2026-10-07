import { Cloud, Laptop } from 'lucide-react';
import type { Engine } from '../lib/api';
import { Segmented } from './ui';

/** Where a video is made: this Mac (best quality, slower) or Cloudflare (fast). */
export function EnginePicker({
    value,
    cloudConnected,
    onChange,
    disabled,
}: {
    value: Engine;
    cloudConnected: boolean;
    onChange: (engine: Engine) => void;
    disabled?: boolean;
}) {
    return (
        <div className={disabled ? 'pointer-events-none opacity-50' : undefined}>
            <Segmented
                size='sm'
                value={value}
                onChange={(engine) => {
                    if (engine === 'cloud' && !cloudConnected) return;
                    onChange(engine);
                }}
                options={[
                    { value: 'local', label: 'This Mac', icon: <Laptop className='h-3.5 w-3.5' />, hint: 'Best quality. About a minute a shot.' },
                    {
                        value: 'cloud',
                        label: 'Cloudflare',
                        icon: <Cloud className='h-3.5 w-3.5' />,
                        hint: cloudConnected ? 'Fast: seconds a shot. Simpler drawings.' : 'Connect Cloudflare in Settings first.',
                    },
                ]}
            />
        </div>
    );
}

export function engineNote(engine: Engine, cloudConnected: boolean) {
    if (engine === 'cloud') {
        return cloudConnected
            ? 'Fast (about 2–3 minutes a video) but simpler drawings. Falls back to this Mac, with a warning, if Cloudflare can’t do it.'
            : 'Cloudflare isn’t connected, so this Mac will make it. Connect it in Settings.';
    }
    return 'Best quality. About a minute a shot; nothing leaves this Mac.';
}
