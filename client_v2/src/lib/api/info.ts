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
	// Spoolman NG fork addition: the daily release check (#293). Optional for the same reason as
	// the three above -- a backend that does not run the check sends none of them, which has to
	// read as "no update to announce" rather than as an error.
	update_available?: boolean;
	latest_version?: string | null;
	release_url?: string | null;
}

export function getInfo(): Promise<Info> {
	return getJson<Info>('/info');
}
