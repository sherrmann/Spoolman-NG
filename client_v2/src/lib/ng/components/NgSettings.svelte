<script lang="ts">
	/**
	 * Every settings panel this fork adds to upstream's settings page, in one mount.
	 *
	 * The page is a vendored upstream file, and each line added to it is a conflict paid on
	 * every subtree pull. This component is that one line; a new panel is added here and costs
	 * the vendored page nothing. Each panel decides for itself whether to render -- all of
	 * them show nothing to a non-administrator.
	 *
	 * The two custom-link lists share one component. The spool-action description names its
	 * placeholders in literal braces (`{id}`), which message-format reads as inputs; feeding
	 * the brace text back in as those inputs renders them as written, in every language, and
	 * saves rewording a string that already has 25 translations.
	 */
	import { ng } from '$lib/ng/i18n';
	import AiSettings from './AiSettings.svelte';
	import CustomLinksSettings from './CustomLinksSettings.svelte';
	import PrinterSettings from './PrinterSettings.svelte';
	import UserSettings from './UserSettings.svelte';

	const braces = {
		id: '{id}',
		filament_id: '{filament_id}',
		location: '{location}',
		lot_nr: '{lot_nr}',
		comment: '{comment}'
	};
</script>

<PrinterSettings />
<CustomLinksSettings
	settingKey="custom_links"
	title={ng.settings_custom_links_nav_tab()}
	description={ng.settings_custom_links_nav_description()}
	urlLabel={ng.settings_custom_links_url()}
	urlPlaceholder="http://mainsail.local"
/>
<CustomLinksSettings
	settingKey="spool_action_links"
	title={ng.settings_custom_links_spool_tab()}
	description={ng.settings_custom_links_spool_description(braces)}
	urlLabel={ng.settings_custom_links_url_template()}
	urlHelp={ng.settings_custom_links_url_template_help({ id: '{id}' })}
	urlPlaceholder="http://moonraker.local/server/spoolman/spool_id?id={'{id}'}"
/>
<UserSettings />
<AiSettings />
