<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   External project links; resolve() is for in-app routes only. */
	/**
	 * The running version and the project links: what upstream's footer carried. The footer is
	 * gone -- on a phone it cost a permanent strip of screen for links nobody needs twice -- so
	 * this sits on the Help page and at the bottom of the phone layout's More sheet instead.
	 */
	import { getInfo, type Info } from '$lib/api/info';
	import * as m from '$lib/paraglide/messages';
	import { ng } from '$lib/ng/i18n';
	import { PROJECT_LINKS } from '$lib/ng/nav';

	interface Props {
		/** Tighter type for the More sheet. */
		compact?: boolean;
	}
	let { compact = false }: Props = $props();

	let info = $state<Info | null>(null);

	$effect(() => {
		getInfo()
			.then((i) => (info = i))
			.catch((e) => console.error('Failed to load version info', e));
	});
</script>

<div class="about" class:compact>
	<p class="version" title={info?.build_date ?? ''}>
		Spoolman NG{#if info}&nbsp;v{info.version}{#if info.git_commit}&nbsp;<span class="commit"
					>({info.git_commit})</span
				>{/if}{/if}
	</p>
	<ul class="links">
		<li>
			<a href={PROJECT_LINKS.documentation} target="_blank" rel="noopener noreferrer"
				>{m['footer.documentation']()}</a
			>
		</li>
		<li>
			<a href={PROJECT_LINKS.issues} target="_blank" rel="noopener noreferrer">{m['footer.reportIssue']()}</a>
		</li>
		<li>
			<a href={PROJECT_LINKS.sponsor} target="_blank" rel="noopener noreferrer"
				>{ng.mobile_nav_sponsor_upstream()}</a
			>
		</li>
	</ul>
</div>

<style>
	.about {
		display: flex;
		flex-direction: column;
		gap: 8px;
		font-size: 13px;
		color: var(--text-dim);
	}
	.about.compact {
		font-size: 12px;
		gap: 4px;
	}
	.version {
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		color: var(--text-2);
		font-weight: 600;
	}
	.commit {
		color: var(--text-faint);
		font-weight: 400;
	}
	.links {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 18px;
	}
	.links a {
		display: inline-block;
		/* A comfortable tap target without looking like a button. */
		padding: 6px 0;
		color: var(--accent-soft);
	}
</style>
