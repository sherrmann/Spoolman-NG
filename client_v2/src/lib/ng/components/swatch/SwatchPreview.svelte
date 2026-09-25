<script lang="ts">
	/**
	 * Spoolman NG fork addition (#415 step 3): a true-to-scale drawing of a swatch layout -- the
	 * exact rectangles that become the printed marking, on the filament's colour. Ported from the
	 * classic client's `components/swatchPreview.tsx`.
	 */
	import type { SwatchLayout } from '$lib/ng/swatch';
	import { basePathD } from '$lib/ng/swatch/preview';

	let { layout, label }: { layout: SwatchLayout; label: string } = $props();

	/** Pixels per mm, so differently sized styles preview at a comparable scale. */
	const PREVIEW_SCALE = 5;

	const uid = $props.id();
	const gradientId = `swatch-gradient-${uid}`;
	let markingFill = $derived(layout.markingColor === 'black' ? '#000000' : '#ffffff');
	let multi = $derived(layout.baseColorHexes.length > 1);
	let baseFill = $derived(multi ? `url(#${gradientId})` : (layout.baseColorHexes[0] ?? '#d9d9d9'));
	// A hanger tab stands above the card's top edge (negative y).
	let overhang = $derived(layout.hangerTab?.outerR ?? 0);
</script>

<svg
	viewBox="0 {-overhang} {layout.widthMm} {layout.heightMm + overhang}"
	style="max-width:{layout.widthMm * PREVIEW_SCALE}px"
	role="img"
	aria-label={label}
>
	{#if multi}
		<defs>
			<linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
				{#each layout.baseColorHexes as hex, i (i)}
					<stop offset={i / (layout.baseColorHexes.length - 1)} stop-color={hex} />
				{/each}
			</linearGradient>
		</defs>
	{/if}
	<path
		d={basePathD(layout)}
		fill-rule="evenodd"
		fill={baseFill}
		stroke="rgba(128, 128, 128, 0.8)"
		stroke-width="0.3"
	/>
	<!-- crispEdges only on the marking: it removes anti-aliasing seams between adjacent QR
	     rects, but would make the card's round corners jaggy. -->
	<g shape-rendering="crispEdges">
		{#each layout.markRects as r, i (i)}
			<rect x={r.x} y={r.y} width={r.w} height={r.h} fill={markingFill} />
		{/each}
	</g>
</svg>

<style>
	svg {
		display: block;
		width: 100%;
		height: auto;
		margin: 0 auto;
	}
</style>
