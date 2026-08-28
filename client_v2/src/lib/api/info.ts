import { getJson } from './http';

// Backend build/runtime info, served once at startup from GET /info.
export interface Info {
	version: string;
	debug_mode: boolean;
	automatic_backups: boolean;
	data_dir: string;
	backups_dir: string;
	db_type: string;
	external_db_name: string;
	git_commit?: string;
	build_date?: string;
	// Per-browser UI switcher (spoolman_ui cookie). Optional because an older backend
	// doesn't send them -- treat their absence the same as "switching is unavailable".
	clients_available?: string[];
	client_active?: string;
	client_switch_enabled?: boolean;
}

export function getInfo(): Promise<Info> {
	return getJson<Info>('/info');
}
