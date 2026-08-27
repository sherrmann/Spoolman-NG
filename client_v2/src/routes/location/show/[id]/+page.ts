import type { PageLoad } from './$types';

// The location id comes from the URL -- this is where a scanned `WEB+SPOOLMAN:L-<id>` label
// lands. Not prerenderable: the id is only known at request time, and per the root +layout.ts
// this app ships as a prerendered SPA shell -- the client-side load below is what actually runs
// once that shell boots, same reasoning as routes/spool/show/[id]/+page.ts.
export const prerender = false;

export const load: PageLoad = ({ params }) => {
	return { id: Number(params.id) };
};
