/**
 * Whether the photo-intake dialog (#418) is open. A store rather than a prop because its two
 * ends are far apart: the scanner opens it, the root layout mounts it.
 */
class PhotoIntakeState {
	open = $state(false);

	show() {
		this.open = true;
	}
	close() {
		this.open = false;
	}
}

export const photoIntake = new PhotoIntakeState();
