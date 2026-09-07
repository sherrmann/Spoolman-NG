// The printer list (#75 / #413), held once for the three places that show it.
//
// The inspector's printer field mounts on every spool selection, the picker on every add-spool
// form, and the registry on the settings page; each fetching its own copy meant thirty list
// requests for thirty arrow presses through the library, and a printer added in Settings
// invisible to a picker already open. Same shape as the custom-link lists.

import { listPrinters } from './api';
import type { Printer } from './types';

class PrinterList {
	items = $state<Printer[]>([]);
	loaded = $state(false);
	private pending: Promise<void> | undefined;

	/** Fetch once. Never throws: an unreachable list is an empty one, and the fields stay hidden. */
	load(): Promise<void> {
		this.pending ??= this.refresh();
		return this.pending;
	}

	/** Fetch again, after a create, edit or delete. */
	async refresh(): Promise<void> {
		try {
			this.items = await listPrinters();
		} catch {
			this.items = [];
		} finally {
			this.loaded = true;
		}
	}
}

export const printers = new PrinterList();
