import 'react-native-url-polyfill/auto';
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = process.env.EXPO_PUBLIC_SUPABASE_URL ?? '';
const supabaseAnonKey = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? '';

export const DEMO_MODE =
  !supabaseUrl ||
  supabaseUrl === 'https://your-project.supabase.co' ||
  process.env.EXPO_PUBLIC_DEMO_MODE === 'true';

export const supabase = DEMO_MODE
  ? null
  : createClient(supabaseUrl, supabaseAnonKey);

// ── Data helpers ──────────────────────────────────────────────────────────

import { Alert, DEMO_PUBLISHED, DEMO_EXTRACTED } from './demo-data';

export async function fetchPublishedAlerts(): Promise<Alert[]> {
  if (DEMO_MODE || !supabase) return DEMO_PUBLISHED;

  const { data, error } = await supabase
    .from('alerts')
    .select('*')
    .in('status', ['PUBLISHED', 'CORRECTED'])
    .order('published_at', { ascending: false });

  if (error) throw error;
  return (data as Alert[]) ?? [];
}

export async function fetchExtractedAlerts(): Promise<Alert[]> {
  if (DEMO_MODE || !supabase) return DEMO_EXTRACTED;

  const { data, error } = await supabase
    .from('alerts')
    .select('*')
    .in('status', ['EXTRACTED', 'EDITOR_REVIEW', 'APPROVED', 'REJECTED'])
    .order('created_at', { ascending: false });

  if (error) throw error;
  return (data as Alert[]) ?? [];
}

export async function updateAlertStatus(id: string, status: string, one_liner?: string): Promise<void> {
  if (DEMO_MODE || !supabase) return;

  const patch: Record<string, string> = { status };
  if (one_liner !== undefined) patch.one_liner = one_liner;

  const { error } = await supabase.from('alerts').update(patch).eq('id', id);
  if (error) throw error;
}

export async function publishApproved(): Promise<void> {
  if (DEMO_MODE || !supabase) return;

  const { error } = await supabase.rpc('publish_approved_alerts');
  if (error) throw error;
}
