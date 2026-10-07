import {
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
    type ButtonHTMLAttributes,
    type ReactNode,
    type SelectHTMLAttributes,
} from 'react';

const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

type Variant = 'primary' | 'secondary' | 'ghost' | 'subtle' | 'danger';
type Size = 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm';

const variants: Record<Variant, string> = {
    primary: 'bg-accent text-accent-fg hover:bg-accent-hover shadow-sm',
    secondary: 'bg-panel-2 text-fg hover:bg-raised border border-line',
    ghost: 'text-muted hover:text-fg hover:bg-panel-2 disabled:hover:bg-transparent',
    subtle: 'bg-panel-2 text-fg hover:bg-raised',
    danger: 'bg-danger-soft text-danger-fg hover:bg-danger/25',
};

const sizes: Record<Size, string> = {
    sm: 'h-8 px-3 text-xs',
    md: 'h-9 px-4 text-sm',
    lg: 'h-11 px-6 text-sm',
    icon: 'h-9 w-9',
    'icon-sm': 'h-8 w-8',
};

export function Button({ variant = 'secondary', size = 'md', className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
    return (
        <button
            className={cx(
                'inline-flex shrink-0 cursor-default items-center justify-center gap-2 rounded-lg font-medium transition-colors',
                'disabled:opacity-40',
                variants[variant],
                sizes[size],
                className
            )}
            {...props}
        />
    );
}

/** Icon-only button. `label` is required: it becomes the tooltip and the accessible name. */
export function IconButton({
    label,
    variant = 'ghost',
    size = 'icon',
    children,
    ...props
}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'title' | 'aria-label'> & { label: string; variant?: Variant; size?: 'icon' | 'icon-sm' }) {
    return (
        <Button variant={variant} size={size} title={label} aria-label={label} {...props}>
            {children}
        </Button>
    );
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
    return (
        <select
            className={cx(
                'h-9 w-full rounded-lg border border-line bg-panel-2 px-3 text-sm text-fg outline-none transition-colors hover:border-line-strong focus:border-accent',
                className
            )}
            {...props}
        >
            {children}
        </select>
    );
}

export function Switch({
    checked,
    onChange,
    disabled,
    label,
}: {
    checked: boolean;
    onChange: (value: boolean) => void;
    disabled?: boolean;
    /** Shown as the tooltip and read by screen readers. */
    label: string;
}) {
    return (
        <button
            role='switch'
            aria-checked={checked}
            aria-label={label}
            title={`${label}: ${checked ? 'on' : 'off'}`}
            disabled={disabled}
            onClick={() => onChange(!checked)}
            className={cx('relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40', checked ? 'bg-accent' : 'bg-line-strong')}
        >
            <span className={cx('absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all', checked ? 'left-[18px]' : 'left-0.5')} />
        </button>
    );
}

/**
 * One-of-many choice. The selected option is marked by an indicator that glides between
 * options (disabled by the reduced-motion setting via index.css).
 */
export function Segmented<T extends string | number>({
    value,
    options,
    onChange,
    size = 'md',
}: {
    value: T;
    options: { value: T; label?: string; icon?: ReactNode; hint?: string }[];
    onChange: (value: T) => void;
    size?: 'sm' | 'md';
}) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);
    const index = options.findIndex((option) => option.value === value);

    useLayoutEffect(() => {
        const container = containerRef.current;
        const place = () => {
            const button = container?.children[index + 1] as HTMLElement | undefined;
            setIndicator(button ? { left: button.offsetLeft, width: button.offsetWidth } : null);
        };
        place();
        if (!container) return;
        const observer = new ResizeObserver(place);
        observer.observe(container);
        return () => observer.disconnect();
    }, [index, options.length]);

    return (
        <div
            ref={containerRef}
            className='relative grid rounded-lg bg-panel-2 p-1'
            // Each option gets at least the room its label needs; the rest is shared equally.
            style={{ gridTemplateColumns: `repeat(${options.length}, minmax(min-content, 1fr))` }}
            role='radiogroup'
        >
            <span
                aria-hidden
                className='absolute top-1 bottom-1 rounded-md bg-accent shadow-sm transition-[left,width] duration-[240ms] ease-in-out'
                style={indicator ? { left: indicator.left, width: indicator.width } : { opacity: 0 }}
            />
            {options.map((option) => {
                const active = option.value === value;
                return (
                    <button
                        key={String(option.value)}
                        role='radio'
                        aria-checked={active}
                        title={option.hint ?? option.label}
                        aria-label={option.label ? undefined : option.hint}
                        onClick={() => onChange(option.value)}
                        className={cx(
                            'relative z-10 flex min-w-0 items-center justify-center gap-1.5 rounded-md px-2 whitespace-nowrap transition-colors [&>svg]:shrink-0',
                            size === 'sm' ? 'h-7 text-xs' : 'h-8 text-sm',
                            active ? 'text-accent-fg' : 'text-muted hover:text-fg'
                        )}
                    >
                        {option.icon}
                        {option.label && <span className='truncate'>{option.label}</span>}
                    </button>
                );
            })}
        </div>
    );
}

/**
 * A centred dialog over a dimmed backdrop. Esc and clicking the backdrop close it unless
 * `dismissable` is false (e.g. while a job is running).
 */
export function Modal({
    onClose,
    dismissable = true,
    className,
    children,
    ...rest
}: {
    onClose: () => void;
    dismissable?: boolean;
    className?: string;
    children: ReactNode;
} & Record<`data-${string}`, unknown>) {
    const closeRef = useRef(onClose);
    closeRef.current = onClose;
    const dismissRef = useRef(dismissable);
    dismissRef.current = dismissable;
    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            if (dismissRef.current) closeRef.current();
        };
        window.addEventListener('keydown', onKey, true);
        return () => window.removeEventListener('keydown', onKey, true);
    }, []);
    return (
        <div
            className='fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-3 backdrop-blur-sm sm:p-6'
            onPointerDown={(e) => e.target === e.currentTarget && dismissable && onClose()}
            {...rest}
        >
            <div className={cx('max-h-full w-full overflow-hidden rounded-2xl border border-line bg-panel shadow-panel', className)} role='dialog' aria-modal>
                {children}
            </div>
        </div>
    );
}

/** A thin progress bar, 0 to 1, with an optional percentage. */
export function ProgressBar({ value, showValue = true }: { value: number; showValue?: boolean }) {
    const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
    return (
        <div className='flex items-center gap-2'>
            <div className='h-1.5 flex-1 overflow-hidden rounded-full bg-line'>
                <div className='h-full rounded-full bg-accent transition-[width] duration-300' style={{ width: `${percent}%` }} />
            </div>
            {showValue && <span className='w-9 text-right font-mono text-xs text-muted'>{percent}%</span>}
        </div>
    );
}

/** A spinning ring for work in progress. */
export function Spinner({ className }: { className?: string }) {
    return <span aria-hidden className={cx('inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent', className)} />;
}

/** A small rounded label. */
export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'warning' | 'success' }) {
    const tones = {
        neutral: 'bg-panel-2 text-muted',
        accent: 'bg-accent/15 text-accent',
        warning: 'bg-warning-soft text-warning-fg',
        success: 'bg-success-soft text-success-fg',
    };
    return <span className={cx('inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium', tones[tone])}>{children}</span>;
}

/** A labelled field. */
export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
    return (
        <div className='space-y-1.5'>
            <div className='flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5'>
                <span className='text-xs font-medium text-fg'>{label}</span>
                {hint && <span className='min-w-0 text-[11px] text-subtle'>{hint}</span>}
            </div>
            {children}
        </div>
    );
}

/** Whether a CSS media query matches, kept up to date as the window resizes. */
export function useMediaQuery(query: string) {
    const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
    useEffect(() => {
        const list = window.matchMedia(query);
        const update = () => setMatches(list.matches);
        update();
        list.addEventListener('change', update);
        return () => list.removeEventListener('change', update);
    }, [query]);
    return matches;
}

export { cx };

