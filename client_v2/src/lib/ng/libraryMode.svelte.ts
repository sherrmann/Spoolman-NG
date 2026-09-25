import { LIBRARY_MODE_KEY, parseStoredMode, type LibraryMode } from './libraryMode';

function read(): LibraryMode {
	try {
		return parseStoredMode(
			typeof localStorage === 'undefined' ? null : localStorage.getItem(LIBRARY_MODE_KEY)
		);
	} catch {
		// Storage disabled (private mode, a blocked third-party context): the list, as shipped.
		return 'list';
	}
}

/** The Library's layout, remembered per browser. See libraryMode.ts. */
class LibraryModeState {
	mode = $state<LibraryMode>(read());

	set(mode: LibraryMode): void {
		this.mode = mode;
		try {
			localStorage.setItem(LIBRARY_MODE_KEY, mode);
		} catch {
			/* remembering the layout is a convenience, not a requirement */
		}
	}
}

export const libraryMode = new LibraryModeState();
