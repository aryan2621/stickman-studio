/** Follows macOS's light or dark appearance (index.css holds both palettes). */
export function initTheme() {
    const media = window.matchMedia('(prefers-color-scheme: light)');
    const apply = () => document.documentElement.setAttribute('data-theme', media.matches ? 'light' : 'dark');
    apply();
    media.addEventListener('change', apply);
}

export function currentTheme(): 'light' | 'dark' {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
}
