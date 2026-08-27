<script lang="ts">
	/* eslint-disable svelte/no-navigation-without-resolve --
	   Generic list component: `href` arrives already resolved against the deploy base
	   path (callers build it with libraryHref()/resolve()), so resolving it again here
	   would double-apply it. Same rationale as Button.svelte's `href` prop. */
	import { truncTitle } from '$lib/actions/truncated';

	// Shared vertical timeline used by Home's "Recently Used" and "Gathering Dust"
	// sections — same dotted rail, same three-line row, differing only in which color
	// and time text the caller hands in per entry.

	export interface TimelineEntry {
		id: number | string;
		href: string;
		name: string;
		detail: string;
		timeLabel: string;
		/** CSS color for the dot and time label; omitted means the neutral default. */
		color?: string;
		/** Glowing, filled dot — the single most-recently-used entry. */
		active?: boolean;
	}

	let { entries }: { entries: TimelineEntry[] } = $props();
</script>

<div class="list">
	{#each entries as e (e.id)}
		<a class="item" href={e.href}>
			<span class="dot" class:active={e.active} style={e.color ? `background:${e.color}` : ''}></span>
			<span class="body">
				<span class="time" style={e.color ? `color:${e.color}` : ''}>{e.timeLabel}</span>
				<span class="name" use:truncTitle>{e.name}</span>
				<span class="detail" use:truncTitle>{e.detail}</span>
			</span>
		</a>
	{/each}
</div>

<style>
	.list {
		display: flex;
		flex-direction: column;
	}
	.item {
		position: relative;
		display: block;
		padding: 0 0 20px 22px;
		margin-left: 4px;
		border-left: 1px solid var(--border-soft);
		color: inherit;
		text-decoration: none;
	}
	.item:last-child {
		border-left-color: transparent;
		padding-bottom: 0;
	}
	.item:hover .name {
		opacity: 0.7;
	}
	.item:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
	.dot {
		position: absolute;
		left: -4px;
		top: 2px;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--border-strong);
	}
	.dot.active {
		background: var(--accent);
		box-shadow: 0 0 10px var(--accent);
	}
	.body {
		display: block;
	}
	.time {
		display: block;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		color: var(--text-faint);
	}
	.name {
		display: block;
		font-size: 13px;
		font-weight: 600;
		margin-top: 3px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		transition: opacity 0.15s;
	}
	.detail {
		display: block;
		font-size: 11px;
		color: var(--text-faint);
		margin-top: 2px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
