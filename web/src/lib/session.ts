import { writable } from 'svelte/store';
import type { SessionInfo } from './api';

export const session = writable<SessionInfo | null>(null);
export const sessionLoaded = writable(false);
