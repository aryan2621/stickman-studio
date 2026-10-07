import React from 'react';
import ReactDOM from 'react-dom/client';
import { Toaster } from 'sonner';
import { App } from './App';
import { currentTheme, initTheme } from './lib/theme';
import './index.css';

initTheme();

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
    <React.StrictMode>
        <App />
        <Toaster theme={currentTheme()} position='bottom-right' richColors />
    </React.StrictMode>
);
