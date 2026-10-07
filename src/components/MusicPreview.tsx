import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { toast } from 'sonner';
import { api, fileUrl } from '../lib/api';
import { IconButton, Spinner } from './ui';

// One player for the whole app, so starting a preview stops any other.
let current: { audio: HTMLAudioElement; stop: () => void } | null = null;

/** Plays a short sample of a music mood, or the user's own music file, to help choose. */
export function MusicPreview({ mood, file }: { mood?: string; file?: string | null }) {
    const [state, setState] = useState<'idle' | 'loading' | 'playing'>('idle');
    const mine = useRef<HTMLAudioElement | null>(null);

    const stop = () => {
        mine.current?.pause();
        if (current?.audio === mine.current) current = null;
        mine.current = null;
        setState('idle');
    };

    // A different choice, or leaving the page, stops the sample.
    useEffect(() => stop, [mood, file]);

    const play = async () => {
        current?.stop();
        setState('loading');
        try {
            const path = file ?? (mood && mood !== 'off' ? await api.musicSample(mood) : null);
            if (!path) return setState('idle');
            const audio = new Audio(fileUrl(path));
            audio.volume = 0.8;
            audio.onended = stop;
            mine.current = audio;
            current = { audio, stop };
            await audio.play();
            // A long music file: a 20-second taste is enough to decide.
            if (file) setTimeout(() => mine.current === audio && stop(), 20000);
            setState('playing');
        } catch (e) {
            stop();
            toast.error(`Couldn’t play the music: ${String(e)}`);
        }
    };

    const disabled = !file && (!mood || mood === 'off');
    return (
        <IconButton
            label={state === 'playing' ? 'Stop the preview' : 'Listen to this music'}
            variant='secondary'
            disabled={disabled}
            onClick={state === 'playing' ? stop : play}
        >
            {state === 'loading' ? <Spinner className='h-3.5 w-3.5' /> : state === 'playing' ? <Pause className='h-4 w-4' /> : <Play className='h-4 w-4' />}
        </IconButton>
    );
}
