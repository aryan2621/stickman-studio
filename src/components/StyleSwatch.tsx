/** A tiny drawn preview of each visual style, for the style picker. */
export function StyleSwatch({ style }: { style: string }) {
    const looks: Record<string, { bg: string; line: string; accent: string; zeke?: boolean; scene?: 'studio' | 'cinema' }> = {
        'classic-light': { bg: '#ffffff', line: '#111111', accent: '#e5382d' },
        'classic-dark': { bg: '#050505', line: '#f5f5f5', accent: '#2ee6f0' },
        'studio-tech': { bg: '#f4f6f9', line: '#111111', accent: '#22c3ee', zeke: true, scene: 'studio' },
        cinematic: { bg: '#2a1d3a', line: '#111111', accent: '#f59e0b', zeke: true, scene: 'cinema' },
    };
    if (style === 'storybook' || style === 'comic') {
        const look = {
            storybook: { sky: ['#fbe8d0', '#fdf6e9'], hill: '#c9dba3', far: '#e4ecc4', coat: '#f2c94c', line: 'none', paper: true },
            comic: { sky: ['#5b3a8c', '#f4884a'], hill: '#3d5a2a', far: '#6b4a7a', coat: '#f2c230', line: '#111', paper: false },
        }[style];
        return (
            <svg viewBox='0 0 160 90' className='block aspect-video w-full' aria-hidden>
                <defs>
                    <linearGradient id={`sky-${style}`} x1='0' y1='0' x2='0' y2='1'>
                        <stop offset='0' stopColor={look.sky[0]} />
                        <stop offset='1' stopColor={look.sky[1]} />
                    </linearGradient>
                </defs>
                <rect width='160' height='90' fill={`url(#sky-${style})`} />
                {look.paper && <rect width='160' height='90' fill='#fff7e8' opacity='0.35' />}
                <path d='M0 58 Q40 40 85 52 T160 46 V90 H0Z' fill={look.far} stroke={look.line} strokeWidth='1.5' />
                <path d='M0 70 Q50 56 100 66 T160 62 V90 H0Z' fill={look.hill} stroke={look.line} strokeWidth='1.5' />
                {/* A small character in a raincoat */}
                <circle cx='70' cy='47' r='5' fill='#f6d7c3' stroke={look.line} strokeWidth='1' />
                <path d='M65 46 Q70 39 75 46 Z' fill='#2b2b2b' />
                <path d='M64 62 L66 52 Q70 50 74 52 L76 62 Z' fill={look.coat} stroke={look.line} strokeWidth='1' />
                <path d='M110 22 l10 -6 l4 10 z' fill='#d94b3d' stroke={look.line} strokeWidth='1' />
                <path d='M74 54 Q95 40 116 26' stroke='#555' strokeWidth='0.6' fill='none' />
            </svg>
        );
    }
    if (style === 'auto') {
        // A quarter of each style: the director picks one.
        return (
            <svg viewBox='0 0 160 90' className='block aspect-video w-full' aria-hidden>
                <rect width='80' height='45' fill='#ffffff' />
                <rect x='80' width='80' height='45' fill='#050505' />
                <rect y='45' width='80' height='45' fill='#f4f6f9' />
                <rect x='80' y='45' width='80' height='45' fill='#3b2a5c' />
                <circle cx='80' cy='45' r='20' fill='#d97757' />
                <path d='M80 31 l3.6 9.4 l9.4 3.6 l-9.4 3.6 l-3.6 9.4 l-3.6 -9.4 l-9.4 -3.6 l9.4 -3.6 z' fill='#ffffff' />
            </svg>
        );
    }
    const look = looks[style] ?? looks['classic-light'];
    return (
        <svg viewBox='0 0 160 90' className='block aspect-video w-full' aria-hidden>
            {look.scene === 'cinema' ? (
                <>
                    <defs>
                        <linearGradient id='dusk' x1='0' y1='0' x2='0' y2='1'>
                            <stop offset='0' stopColor='#3b2a5c' />
                            <stop offset='0.6' stopColor='#c2593b' />
                            <stop offset='1' stopColor='#f2b04a' />
                        </linearGradient>
                    </defs>
                    <rect width='160' height='90' fill='url(#dusk)' />
                    <path d='M0 70 Q40 55 80 66 T160 62 V90 H0Z' fill='#2b1b2e' />
                    <circle cx='122' cy='40' r='10' fill='#ffd27a' opacity='0.9' />
                </>
            ) : (
                <rect width='160' height='90' fill={look.bg} />
            )}
            {look.scene === 'studio' && (
                <>
                    {[0, 1, 2, 3, 4].map((i) => (
                        <line key={i} x1={80} y1={58} x2={-40 + i * 60} y2={90} stroke='#dfe3ea' strokeWidth='0.8' />
                    ))}
                    <line x1='0' y1='70' x2='160' y2='70' stroke='#dfe3ea' strokeWidth='0.8' />
                    <rect x='104' y='18' width='34' height='22' rx='4' fill={look.accent} opacity='0.25' stroke={look.accent} strokeWidth='1' />
                </>
            )}
            {!look.zeke && <circle cx='112' cy='34' r='9' fill='none' stroke={look.accent} strokeWidth='2.5' />}
            {/* The figure */}
            <g stroke={look.line} strokeWidth='2.4' strokeLinecap='round' fill='none'>
                <circle cx='62' cy='28' r='7' fill={look.zeke ? '#ffffff' : 'none'} />
                <line x1='62' y1='35' x2='62' y2='56' stroke={look.zeke ? '#111' : look.line} />
                <line x1='62' y1='41' x2='50' y2='50' />
                <line x1='62' y1='41' x2='76' y2='33' />
                <line x1='62' y1='56' x2='54' y2='72' />
                <line x1='62' y1='56' x2='70' y2='72' />
            </g>
            {look.zeke && (
                <>
                    <path d='M55 26 Q62 15 69 26 Z' fill='#e5382d' />
                    <rect x='57.5' y='36' width='9' height='13' rx='2' fill='#facc15' />
                    <circle cx='60' cy='29' r='0.9' fill='#111' />
                    <circle cx='64.5' cy='29' r='0.9' fill='#111' />
                </>
            )}
        </svg>
    );
}
