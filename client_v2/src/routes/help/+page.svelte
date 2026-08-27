<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   Every href below is built from resolve()'s own result; resolving again would
	   double-apply the deploy base path. Same pattern as routes/home/+page.svelte. */
	// The Help page, ported from client/src/pages/help/index.tsx.
	//
	// Its copy is one message -- `help.description` -- carrying <Trans>-style markup, because
	// the links sit INSIDE the sentences. $lib/ng/trans parses it into blocks and inline runs
	// which this page renders as ordinary Svelte elements, so all 32 existing translations
	// survive and no markup from a translation can reach the DOM (there is no {@html} here).
	//
	// The three create links point at the Library views where each entity is created rather
	// than at React's /filament/create, /spool/create and /vendor/create: this client has no
	// create ROUTES at all -- creation happens in modals opened from the Library -- so the
	// list view is the honest destination. routes/home/+page.svelte's KPI cards resolve the
	// same three targets the same way.
	import { resolve } from '$app/paths';
	import { ng } from '$lib/ng/i18n';
	import { parseTrans, type Inline } from '$lib/ng/trans';
	import Highlighter from '@lucide/svelte/icons/highlighter';
	import FileText from '@lucide/svelte/icons/file-text';
	import User from '@lucide/svelte/icons/user';

	const libraryHref = resolve('/');
	const spoolListHref = `${libraryHref}?group=none`;
	const vendorListHref = `${libraryHref}?group=vendor`;
	const README = 'https://github.com/sherrmann/Spoolman-NG#integrations';

	/** Where each named link in the message points. An unknown name renders as plain text. */
	const LINKS: Record<string, string> = {
		filamentCreateLink: libraryHref,
		spoolCreateLink: spoolListHref,
		vendorCreateLink: vendorListHref,
		readmeLink: README
	};

	const RESOURCES = [
		{ icon: Highlighter, title: ng.filament_filament, body: ng.help_resources_filament },
		{ icon: FileText, title: ng.spool_spool, body: ng.help_resources_spool },
		{ icon: User, title: ng.vendor_vendor, body: ng.help_resources_vendor }
	];

	let blocks = $derived(parseTrans(ng.help_description()));

	const isExternal = (href: string) => href.startsWith('http');
</script>

<svelte:head>
	<title>{ng.help_help()} | Spoolman</title>
</svelte:head>

{#snippet inline(nodes: Inline[])}
	{#each nodes as node, i (i)}
		{#if node.kind === 'text'}{node.text}{:else if LINKS[node.name]}<a
				href={LINKS[node.name]}
				target={isExternal(LINKS[node.name]) ? '_blank' : undefined}
				rel={isExternal(LINKS[node.name]) ? 'noreferrer' : undefined}>{node.text}</a
			>{:else}{node.text}{/if}
	{/each}
{/snippet}

<div class="page scroll-y">
	<h1>{ng.help_help()}</h1>

	<div class="card">
		{#each blocks as block, i (i)}
			{#if block.kind === 'void' && block.name === 'itemsHelp'}
				<ul class="resources">
					{#each RESOURCES as resource (resource.title)}
						{@const Icon = resource.icon}
						<li>
							<span class="res-icon"><Icon size={20} /></span>
							<span class="res-body">
								<strong>{resource.title()}</strong>
								<span>{resource.body()}</span>
							</span>
						</li>
					{/each}
				</ul>
			{:else if block.kind === 'block' && block.name !== 'title'}
				<!-- The message opens with its own <title>Help</title>, which react-i18next
				     rendered as the page heading. This page already has an <h1> from the same
				     key, so rendering it again just says "Help" twice. Skipped rather than
				     restyled: it is a duplicate, not a section heading. -->
				<p>{@render inline(block.inline)}</p>
			{/if}
		{/each}
	</div>
</div>

<style>
	.page {
		max-width: 860px;
		width: 100%;
		margin: 0 auto;
		padding: 20px 22px 40px;
		display: flex;
		flex-direction: column;
		gap: 20px;
	}
	h1 {
		margin: 0;
		font-size: 20px;
		font-weight: 800;
		letter-spacing: -0.02em;
	}
	.card {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: var(--radius-lg);
		padding: 20px 22px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.card p {
		margin: 0;
		font-size: 13.5px;
		line-height: 1.7;
		color: var(--text-2);
	}
	.card a {
		color: var(--accent-soft);
	}

	.resources {
		list-style: none;
		margin: 4px 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.resources li {
		display: flex;
		align-items: flex-start;
		gap: 12px;
	}
	.res-icon {
		flex: none;
		display: inline-flex;
		color: var(--accent-soft);
		margin-top: 2px;
	}
	.res-body {
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 13px;
		color: var(--text-dim);
	}
	.res-body strong {
		font-size: 13.5px;
		color: var(--text);
	}
</style>
