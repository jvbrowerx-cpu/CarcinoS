import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Modal,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useState, useEffect } from 'react';
import { colors } from '../../constants/theme';
import { supabase, DEMO_MODE } from '../../lib/supabase';

// ── Types ─────────────────────────────────────────────────────────────────────

type OncologyScope = 'all' | 'radiation_only';
type DeliveryChannel = 'email' | 'push' | 'both';

interface SiteConfig {
  code: string;
  label: string;
}

const DISEASE_SITES: SiteConfig[] = [
  { code: 'breast',          label: 'Breast' },
  { code: 'thoracic',        label: 'Thoracic' },
  { code: 'gastrointestinal',label: 'Gastrointestinal' },
  { code: 'gu',              label: 'Genitourinary' },
  { code: 'gynecologic',     label: 'Gynecologic' },
  { code: 'head_neck',       label: 'Head & Neck' },
  { code: 'hematologic',     label: 'Hematologic' },
  { code: 'cns',             label: 'CNS' },
  { code: 'cutaneous',       label: 'Cutaneous' },
  { code: 'sarcoma',         label: 'Sarcoma' },
];

// ── Demo preferences (replace with real Supabase fetch in production) ─────────

const DEMO_PREFS = {
  scope: 'all' as OncologyScope,
  sites: DISEASE_SITES.map(s => s.code),
  delivery: 'email' as DeliveryChannel,
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionHeader({ title }: { title: string }) {
  return <Text style={styles.sectionHeader}>{title}</Text>;
}

function RowItem({
  label,
  value,
  onPress,
  last,
}: {
  label: string;
  value?: string;
  onPress?: () => void;
  last?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[styles.row, last && styles.rowLast]}
      onPress={onPress}
      activeOpacity={onPress ? 0.7 : 1}
    >
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.rowRight}>
        {value ? <Text style={styles.rowValue}>{value}</Text> : null}
        {onPress ? <Text style={styles.rowChevron}>›</Text> : null}
      </View>
    </TouchableOpacity>
  );
}

// ── Scope edit modal ──────────────────────────────────────────────────────────

function ScopeModal({
  visible,
  current,
  onSave,
  onClose,
}: {
  visible: boolean;
  current: OncologyScope;
  onSave: (s: OncologyScope) => void;
  onClose: () => void;
}) {
  const [sel, setSel] = useState<OncologyScope>(current);
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.editModal}>
        <View style={styles.editHandle} />
        <Text style={styles.editTitle}>Oncology Coverage</Text>

        {(['all', 'radiation_only'] as OncologyScope[]).map(scope => (
          <TouchableOpacity
            key={scope}
            style={[styles.optionCard, sel === scope && styles.optionCardSelected]}
            onPress={() => setSel(scope)}
            activeOpacity={0.78}
          >
            <View style={styles.optionCardLeft}>
              <Text style={styles.optionCardTitle}>
                {scope === 'all' ? 'All Oncology' : 'Radiation Oncology Only'}
              </Text>
              <Text style={styles.optionCardSub}>
                {scope === 'all'
                  ? 'All tiers across your selected disease sites'
                  : 'Only alerts with direct radiation oncology relevance'}
              </Text>
            </View>
            <View style={[styles.optionDot, sel === scope && styles.optionDotSelected]} />
          </TouchableOpacity>
        ))}

        <TouchableOpacity style={styles.saveBtn} onPress={() => { onSave(sel); onClose(); }}>
          <Text style={styles.saveBtnText}>Save</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
          <Text style={styles.cancelBtnText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

// ── Sites edit modal ──────────────────────────────────────────────────────────

function SitesModal({
  visible,
  current,
  onSave,
  onClose,
}: {
  visible: boolean;
  current: string[];
  onSave: (sites: string[]) => void;
  onClose: () => void;
}) {
  const [sel, setSel] = useState<string[]>(current);
  const toggle = (code: string) =>
    setSel(prev => prev.includes(code) ? prev.filter(c => c !== code) : [...prev, code]);
  const allSelected = DISEASE_SITES.every(s => sel.includes(s.code));

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.editModal}>
        <View style={styles.editHandle} />
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <Text style={styles.editTitle}>Disease Sites</Text>
          <TouchableOpacity onPress={() => setSel(allSelected ? [] : DISEASE_SITES.map(s => s.code))}>
            <Text style={{ color: colors.green, fontSize: 13, fontWeight: '600' }}>
              {allSelected ? 'Deselect all' : 'Select all'}
            </Text>
          </TouchableOpacity>
        </View>
        <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
          <View style={styles.siteGrid}>
            {DISEASE_SITES.map(site => {
              const checked = sel.includes(site.code);
              return (
                <TouchableOpacity
                  key={site.code}
                  style={[styles.siteChip, checked && styles.siteChipSelected]}
                  onPress={() => toggle(site.code)}
                  activeOpacity={0.7}
                >
                  <Text style={[styles.siteChipText, checked && { color: '#fff' }]}>
                    {checked ? '✓ ' : ''}{site.label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
          <View style={{ height: 20 }} />
        </ScrollView>
        <TouchableOpacity
          style={[styles.saveBtn, !sel.length && { opacity: 0.4 }]}
          onPress={() => { if (sel.length) { onSave(sel); onClose(); } }}
        >
          <Text style={styles.saveBtnText}>Save {sel.length ? `(${sel.length})` : ''}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
          <Text style={styles.cancelBtnText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

// ── Delivery edit modal ───────────────────────────────────────────────────────

function DeliveryModal({
  visible,
  current,
  onSave,
  onClose,
}: {
  visible: boolean;
  current: DeliveryChannel;
  onSave: (d: DeliveryChannel) => void;
  onClose: () => void;
}) {
  const [sel, setSel] = useState<DeliveryChannel>(current);
  const opts: { value: DeliveryChannel; icon: string; label: string; sub: string }[] = [
    { value: 'email', icon: '✉️', label: 'Email digest', sub: 'Weekly email every Monday' },
    { value: 'push',  icon: '🔔', label: 'Push only',    sub: 'In-app alerts for Practice Impacting findings' },
    { value: 'both',  icon: '📲', label: 'Both',         sub: 'Email + push for critical updates' },
  ];

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={styles.editModal}>
        <View style={styles.editHandle} />
        <Text style={styles.editTitle}>Delivery Method</Text>
        {opts.map(opt => (
          <TouchableOpacity
            key={opt.value}
            style={[styles.optionCard, sel === opt.value && styles.optionCardSelected]}
            onPress={() => setSel(opt.value)}
            activeOpacity={0.78}
          >
            <Text style={{ fontSize: 22, marginRight: 14 }}>{opt.icon}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.optionCardTitle}>{opt.label}</Text>
              <Text style={styles.optionCardSub}>{opt.sub}</Text>
            </View>
            <View style={[styles.optionDot, sel === opt.value && styles.optionDotSelected]} />
          </TouchableOpacity>
        ))}
        <TouchableOpacity style={styles.saveBtn} onPress={() => { onSave(sel); onClose(); }}>
          <Text style={styles.saveBtnText}>Save</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
          <Text style={styles.cancelBtnText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </Modal>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export default function SettingsScreen() {
  const [scope, setScope] = useState<OncologyScope>(DEMO_PREFS.scope);
  const [sites, setSites] = useState<string[]>(DEMO_PREFS.sites);
  const [delivery, setDelivery] = useState<DeliveryChannel>(DEMO_PREFS.delivery);

  const [showScope, setShowScope] = useState(false);
  const [showSites, setShowSites] = useState(false);
  const [showDelivery, setShowDelivery] = useState(false);
  const [saving, setSaving] = useState(false);

  // Load real preferences from Supabase on mount
  useEffect(() => {
    if (DEMO_MODE || !supabase) return;
    (async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return;
      const uid = session.user.id;

      // Fetch scope + tier from user_preferences
      const { data: prefs } = await supabase
        .from('user_preferences')
        .select('specialty, min_tier')
        .eq('user_id', uid)
        .maybeSingle();
      if (prefs) {
        setScope(prefs.specialty === 'radiation_oncology' ? 'radiation_only' : 'all');
      }

      // Fetch delivery from users table
      const { data: userRow } = await supabase
        .from('users')
        .select('delivery')
        .eq('id', uid)
        .maybeSingle();
      if (userRow?.delivery) setDelivery(userRow.delivery as DeliveryChannel);

      // Fetch active site subscriptions
      const { data: subs } = await supabase
        .from('subscriptions')
        .select('disease_site_id, is_active')
        .eq('user_id', uid);
      if (subs && subs.length > 0) {
        const { data: sitesData } = await supabase
          .from('disease_sites')
          .select('id, code');
        if (sitesData) {
          const idToCode: Record<string, string> = {};
          sitesData.forEach(s => { idToCode[s.id] = s.code; });
          const activeCodes = subs
            .filter(s => s.is_active)
            .map(s => idToCode[s.disease_site_id])
            .filter(Boolean);
          if (activeCodes.length > 0) setSites(activeCodes);
        }
      }
    })();
  }, []);

  // Save preferences to Supabase
  async function savePreferences() {
    if (DEMO_MODE || !supabase) {
      Alert.alert('Demo Mode', 'Preferences saved locally (demo mode).');
      return;
    }
    setSaving(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) throw new Error('Not signed in');
      const uid = session.user.id;

      // Map scope back to specialty_group enum value
      const specialty = scope === 'radiation_only' ? 'radiation_oncology' : 'all_oncology';

      // 1. Update delivery on users table
      await supabase.from('users').update({ delivery }).eq('id', uid);

      // 2. Upsert user_preferences
      await supabase.from('user_preferences').upsert({
        user_id:      uid,
        specialty,
        email_opt_in: delivery !== 'push',
      }, { onConflict: 'user_id' });

      // 3. Fetch all disease_sites to get IDs
      const { data: allSitesData } = await supabase
        .from('disease_sites')
        .select('id, code');
      if (allSitesData) {
        const rows = allSitesData.map(site => ({
          user_id:         uid,
          disease_site_id: site.id,
          is_active:       sites.includes(site.code),
          notify_tier_a:   true,
          notify_tier_b:   true,
          email_opt_in:    delivery !== 'push',
          push_opt_in:     delivery !== 'email',
        }));
        await supabase
          .from('subscriptions')
          .upsert(rows, { onConflict: 'user_id,disease_site_id' });
      }

      Alert.alert('Saved', 'Your preferences have been updated.');
    } catch (err: any) {
      Alert.alert('Error', err.message || 'Failed to save. Please try again.');
    } finally {
      setSaving(false);
    }
  }

  const scopeLabel = scope === 'all' ? 'All Oncology' : 'Radiation Only';
  const sitesLabel = sites.length === DISEASE_SITES.length
    ? 'All sites'
    : `${sites.length} site${sites.length === 1 ? '' : 's'}`;
  const deliveryLabel = delivery === 'email' ? 'Email' : delivery === 'push' ? 'Push' : 'Email + Push';

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* Nav */}
      <View style={styles.nav}>
        <View style={styles.brand}>
          <View style={styles.logoBox}>
            <Text style={styles.logoText}>C<Text style={{ color: colors.green }}>S</Text></Text>
          </View>
          <Text style={styles.brandName}>Carcino<Text style={{ color: colors.green }}>S</Text></Text>
        </View>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text style={styles.pageTitle}>Preferences</Text>
        <Text style={styles.pageSub}>Customise what you receive and how.</Text>

        {/* Coverage */}
        <SectionHeader title="COVERAGE" />
        <View style={styles.card}>
          <RowItem
            label="Oncology scope"
            value={scopeLabel}
            onPress={() => setShowScope(true)}
          />
          <RowItem
            label="Disease sites"
            value={sitesLabel}
            onPress={() => setShowSites(true)}
            last
          />
        </View>

        {/* Site summary chips */}
        {sites.length < DISEASE_SITES.length && (
          <View style={styles.chipRow}>
            {sites.map(code => {
              const site = DISEASE_SITES.find(s => s.code === code);
              return site ? (
                <View key={code} style={styles.chip}>
                  <Text style={styles.chipText}>{site.label}</Text>
                </View>
              ) : null;
            })}
          </View>
        )}

        {/* Notifications */}
        <SectionHeader title="NOTIFICATIONS" />
        <View style={styles.card}>
          <RowItem
            label="Delivery method"
            value={deliveryLabel}
            onPress={() => setShowDelivery(true)}
            last
          />
        </View>

        {/* About */}
        <SectionHeader title="ABOUT" />
        <View style={styles.card}>
          <RowItem label="Version" value="1.0.0" last />
        </View>

        {/* Save */}
        <TouchableOpacity
          style={[styles.saveBtn, saving && { opacity: 0.6 }]}
          onPress={savePreferences}
          disabled={saving}
          activeOpacity={0.8}
        >
          {saving
            ? <ActivityIndicator color="#fff" size="small" />
            : <Text style={styles.saveBtnText}>Save Preferences</Text>
          }
        </TouchableOpacity>

        <Text style={styles.footer}>
          Preferences are applied to your weekly digest and push notifications.{'\n'}
          CarcinoS · oncology intelligence for clinicians
        </Text>
      </ScrollView>

      {/* Modals */}
      <ScopeModal
        visible={showScope}
        current={scope}
        onSave={setScope}
        onClose={() => setShowScope(false)}
      />
      <SitesModal
        visible={showSites}
        current={sites}
        onSave={setSites}
        onClose={() => setShowSites(false)}
      />
      <DeliveryModal
        visible={showDelivery}
        current={delivery}
        onSave={setDelivery}
        onClose={() => setShowDelivery(false)}
      />
    </SafeAreaView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: 'rgba(6,6,9,0.92)',
  },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  logoBox: {
    width: 32, height: 32,
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.6)',
    borderRadius: 7, backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center', justifyContent: 'center',
  },
  logoText: { fontFamily: 'Georgia', fontSize: 13, fontWeight: '800', color: '#fff' },
  brandName: { fontSize: 16, fontWeight: '700', color: '#fff', letterSpacing: -0.3 },

  scroll: { flex: 1 },
  content: { padding: 20, paddingBottom: 60 },
  pageTitle: { fontSize: 26, fontWeight: '800', color: '#fff', letterSpacing: -0.5, marginBottom: 4 },
  pageSub: { fontSize: 14, color: colors.grey, marginBottom: 28 },

  sectionHeader: {
    fontSize: 10, fontWeight: '700', color: colors.grey,
    letterSpacing: 1.2, marginBottom: 8, marginTop: 20, marginLeft: 2,
  },

  card: {
    backgroundColor: colors.cardBg,
    borderRadius: 14,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
  },
  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingVertical: 15,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  rowLast: { borderBottomWidth: 0 },
  rowLabel: { fontSize: 15, color: '#fff', fontWeight: '500' },
  rowRight: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  rowValue: { fontSize: 14, color: colors.grey },
  rowChevron: { fontSize: 18, color: 'rgba(255,255,255,0.25)' },

  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 10 },
  chip: {
    backgroundColor: colors.greenDim,
    borderWidth: 1, borderColor: colors.greenBorder,
    borderRadius: 6, paddingHorizontal: 10, paddingVertical: 4,
  },
  chipText: { fontSize: 12, color: colors.green, fontWeight: '600' },

  footer: {
    textAlign: 'center', fontSize: 12, color: 'rgba(255,255,255,0.2)',
    marginTop: 40, lineHeight: 18,
  },

  // Edit modals
  editModal: {
    flex: 1,
    backgroundColor: colors.bg,
    paddingHorizontal: 24,
    paddingTop: 16,
    paddingBottom: 40,
  },
  editHandle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignSelf: 'center', marginBottom: 24,
  },
  editTitle: {
    fontSize: 20, fontWeight: '800', color: '#fff',
    letterSpacing: -0.4, marginBottom: 20,
  },

  optionCard: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 14, padding: 16, marginBottom: 10,
  },
  optionCardSelected: { borderColor: colors.green, backgroundColor: 'rgba(106,184,122,0.08)' },
  optionCardLeft: { flex: 1 },
  optionCardTitle: { fontSize: 15, fontWeight: '700', color: '#fff', marginBottom: 3 },
  optionCardSub: { fontSize: 12, color: colors.grey, lineHeight: 17 },
  optionDot: {
    width: 18, height: 18, borderRadius: 9,
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.25)',
    marginLeft: 12,
  },
  optionDotSelected: { borderColor: colors.green, backgroundColor: colors.green },

  siteGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  siteChip: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.12)',
    borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10,
  },
  siteChipSelected: { borderColor: colors.green, backgroundColor: 'rgba(106,184,122,0.1)' },
  siteChipText: { fontSize: 13, fontWeight: '600', color: 'rgba(255,255,255,0.6)' },

  saveBtn: {
    backgroundColor: colors.green,
    borderRadius: 12, paddingVertical: 16,
    alignItems: 'center', marginTop: 16,
  },
  saveBtnText: { fontSize: 15, fontWeight: '700', color: '#fff' },
  cancelBtn: {
    borderRadius: 12, paddingVertical: 14,
    alignItems: 'center', marginTop: 8,
  },
  cancelBtnText: { fontSize: 14, color: colors.grey },
});
