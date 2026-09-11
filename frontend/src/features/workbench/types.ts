import type { GuidedFields } from './GuidedEntry';

export type Evidence = { title: string; url: string; claim: string; published_at: string; status: string };
export type Card = GuidedFields & { id: string; name: string; code: string; theme: string; status: string; evidence: Evidence[]; updated_at: string; confirmed_at: string };
export type Snapshot = { revision: number; cards: Card[] };
