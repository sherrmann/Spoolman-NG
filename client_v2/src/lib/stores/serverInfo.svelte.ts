import { getInfo } from '$lib/api/info';

// Runtime info served once at startup from GET /info. Kept in a tiny store so
// components can read operator-configured values (like the external library's
// display name) without each re-fetching /info.

class ServerInfo {
	// Display name for the external filament library (EXTERNAL_DB_NAME on the
	// backend, "SpoolmanDB" by default). Used as the label/badge for external
	// results and interpolated into localized strings via the {name} parameter.
	externalDbName = $state('SpoolmanDB');
	loaded = $state(false);

	// Per-browser UI switcher (spoolman_ui cookie, see $lib/uiClient). These three default to
	// "switching is unavailable" -- an older backend that has never heard of the switcher sends
	// none of them, and that must read the same as one that has it turned off.
	clientsAvailable = $state<string[]>([]);
	clientActive = $state<string | null>(null);
	clientSwitchEnabled = $state(false);

	async load() {
		try {
			const info = await getInfo();
			if (info.external_db_name) this.externalDbName = info.external_db_name;
			if (info.clients_available) this.clientsAvailable = info.clients_available;
			if (info.client_active) this.clientActive = info.client_active;
			this.clientSwitchEnabled = info.client_switch_enabled === true;
		} catch (e) {
			console.error('Failed to load server info', e);
		} finally {
			this.loaded = true;
		}
	}
}

export const serverInfo = new ServerInfo();
