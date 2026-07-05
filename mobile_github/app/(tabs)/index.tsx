import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Modal,
  SafeAreaView as RNSafeArea,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useState, useEffect } from 'react';
import { colors, tiers, TierCode } from '../../constants/theme';
import { Alert, DEMO_PUBLISHED, WEEK_LABEL, SCAN_LABEL } from '../../lib/demo-data';
import { fetchPublishedAlerts, DEMO_MODE } from '../../lib/supabase';

// ── Alert detail modal ───────────────────────────────────────────────────────

function AlertDetailModal({ alert, onClose }: { alert: Alert; onClose: () => void }) {
  const tier = tiers[alert.tier];
  return (
    <Modal animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <RNSafeArea style={[styles.modalSafe, { backgroundColor: colors.cardBg }]}>
        <View style={styles.modalHandle} />
        <ScrollView style={styles.modalScroll} showsVerticalScrollIndicator={false}>
          {/* Tier badge */}
          <View style={[styles.modalTierBadge, { backgroundColor: tier.bg }]}>
            <Text style={[styles.modalTierText, { color: tier.text }]}>{tier.shortLabel}</Text>
          </View>

          {/* Title */}
          <Text style={styles.modalTitle}>{alert.title}</Text>

          {/* Meta row */}
          <View style={styles.modalMeta}>
            <Text style={styles.modalMetaText}>{alert.journal}</Text>
            {alert.phase && <Text style={styles.modalMetaDot}> · </Text>}
            {alert.phase && <Text style={styles.modalMetaText}>{alert.phase}</Text>}
            <Text style={styles.modalMetaDot}> · </Text>
            <Text style={styles.modalMetaText}>{alert.disease_site}</Text>
          </View>

          {/* Key result */}
          {alert.result && (
            <View style={styles.modalResultBox}>
              <Text style={styles.modalResultLabel}>KEY RESULT</Text>
              <Text style={styles.modalResultText}>{alert.result}</Text>
            </View>
          )}

          {/* Rule */}
          <View style={styles.rule} />

          {/* One-liner */}
          <Text style={styles.modalSectionLabel}>CLINICAL TAKE</Text>
          <Text style={styles.modalOneLiner}>{alert.one_liner}</Text>

          {/* Context */}
          {alert.context && (
            <>
              <Text style={[styles.modalSectionLabel, { marginTop: 24 }]}>CONTEXT</Text>
              <Text style={styles.modalContext}>{alert.context}</Text>
            </>
          )}

          {/* Key quote */}
          {alert.key_quote && (
            <View style={styles.quoteBox}>
              <Text style={styles.quoteText}>&ldquo;{alert.key_quote}&rdquo;</Text>
            </View>
          )}

          {/* PMID */}
          {alert.pmid && (
            <Text style={styles.pmid}>PMID: {alert.pmid}</Text>
          )}

          <View style={{ height: 40 }} />
        </ScrollView>

        <TouchableOpacity style={styles.modalCloseBtn} onPress={onClose}>
          <Text style={styles.modalCloseBtnText}>Close</Text>
        </TouchableOpacity>
      </RNSafeArea>
    </Modal>
  );
}

// ── Alert card ───────────────────────────────────────────────────────────────

function AlertCard({ alert, onPress }: { alert: Alert; onPress: () => void }) {
  const tier = tiers[alert.tier];
  return (
    <TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.78}>
      <View style={styles.cardBody}>
        <Text style={styles.cardTitle}>{alert.title}</Text>
        <Text style={styles.cardMeta}>
          {alert.journal}{alert.phase ? ` · ${alert.phase}` : ''} · {alert.disease_site}
        </Text>
        {alert.result && (
          <Text style={[styles.cardResult, alert.tier === 'PI' && { color: colors.green }]}>
            {alert.result}
          </Text>
        )}
      </View>
      <Text style={styles.cardChevron}>›</Text>
    </TouchableOpacity>
  );
}

// ── Tier section ─────────────────────────────────────────────────────────────

function TierSection({
  tierCode,
  alerts,
  onPress,
}: {
  tierCode: TierCode;
  alerts: Alert[];
  onPress: (a: Alert) => void;
}) {
  const tier = tiers[tierCode];
  if (alerts.length === 0) return null;

  return (
    <View style={styles.section}>
      <View style={[styles.sectionHeader, { backgroundColor: tier.bg }]}>
        <Text style={[styles.sectionHeaderText, { color: tier.text }]}>{tier.shortLabel}</Text>
        <Text style={[styles.sectionHeaderCount, { color: tier.text, opacity: 0.6 }]}>
          {alerts.length} {alerts.length === 1 ? 'update' : 'updates'}
        </Text>
      </View>
      {alerts.map((a) => (
        <AlertCard key={a.id} alert={a} onPress={() => onPress(a)} />
      ))}
    </View>
  );
}

// ── Screen ───────────────────────────────────────────────────────────────────

export default function ThisWeekScreen() {
  const [alerts, setAlerts] = useState<Alert[]>(DEMO_PUBLISHED);
  const [selected, setSelected] = useState<Alert | null>(null);
  const [loading, setLoading] = useState(!DEMO_MODE);

  useEffect(() => {
    if (DEMO_MODE) return;
    fetchPublishedAlerts()
      .then(setAlerts)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const pi = alerts.filter((a) => a.tier === 'PI');
  const inc = alerts.filter((a) => a.tier === 'INC');
  const hor = alerts.filter((a) => a.tier === 'HOR');

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* Nav */}
      <View style={styles.nav}>
        <View style={styles.brand}>
          <View style={styles.logoBox}>
            <Text style={styles.logoText}>
              C<Text style={{ color: colors.green }}>S</Text>
            </Text>
          </View>
          <Text style={styles.brandName}>
            Carcino<Text style={{ color: colors.green }}>S</Text>
          </Text>
        </View>
        <View style={styles.weekBadge}>
          <Text style={styles.weekBadgeText}>{WEEK_LABEL}</Text>
        </View>
      </View>

      {/* Status row */}
      <View style={styles.statusRow}>
        <Ionicons name="checkmark-circle" size={14} color={colors.green} />
        <Text style={styles.statusText}>
          <Text style={{ color: '#fff', fontWeight: '700' }}>Up to date</Text>
          {'  ·  ' + SCAN_LABEL}
        </Text>
        {DEMO_MODE && (
          <View style={styles.demoBadge}>
            <Text style={styles.demoBadgeText}>DEMO</Text>
          </View>
        )}
      </View>

      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        <TierSection tierCode="PI" alerts={pi} onPress={setSelected} />
        <TierSection tierCode="INC" alerts={inc} onPress={setSelected} />
        <TierSection tierCode="HOR" alerts={hor} onPress={setSelected} />

        <Text style={styles.footer}>
          Pipeline run · {alerts.length} alerts published · CarcinoS
        </Text>
      </ScrollView>

      {selected && (
        <AlertDetailModal alert={selected} onClose={() => setSelected(null)} />
      )}
    </SafeAreaView>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },

  // Nav
  nav: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
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
  weekBadge: {
    backgroundColor: colors.greenDim,
    borderWidth: 1, borderColor: colors.greenBorder,
    borderRadius: 5, paddingHorizontal: 8, paddingVertical: 4,
  },
  weekBadgeText: { fontSize: 10, fontWeight: '700', color: colors.green, letterSpacing: 0.6 },

  // Status
  statusRow: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: 20, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.borderDim,
  },
  statusText: { fontSize: 12, color: colors.grey, flex: 1 },
  demoBadge: {
    backgroundColor: 'rgba(240,168,67,0.15)',
    borderWidth: 1, borderColor: 'rgba(240,168,67,0.4)',
    borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2,
  },
  demoBadgeText: { fontSize: 9, fontWeight: '800', color: colors.pending, letterSpacing: 0.8 },

  // Scroll
  scroll: { flex: 1 },
  scrollContent: { paddingTop: 16, paddingHorizontal: 16, paddingBottom: 40 },

  // Section
  section: {
    marginBottom: 16,
    borderRadius: 14,
    overflow: 'hidden',
  },
  sectionHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 14, paddingVertical: 10,
  },
  sectionHeaderText: { fontSize: 10, fontWeight: '800', letterSpacing: 0.8 },
  sectionHeaderCount: { fontSize: 10, fontWeight: '500' },

  // Card
  card: {
    flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between',
    backgroundColor: '#ffffff',
    paddingHorizontal: 14, paddingVertical: 12,
    borderTopWidth: 1, borderTopColor: 'rgba(0,0,0,0.07)',
    gap: 8,
  },
  cardBody: { flex: 1 },
  cardTitle: { fontSize: 13, fontWeight: '700', color: '#111', lineHeight: 18, marginBottom: 3 },
  cardMeta: { fontSize: 11, color: '#888', marginBottom: 2 },
  cardResult: { fontSize: 11, color: '#888' },
  cardChevron: { fontSize: 18, color: 'rgba(0,0,0,0.25)', marginTop: 1 },

  // Footer
  footer: {
    textAlign: 'center', fontSize: 12, color: 'rgba(255,255,255,0.2)', marginTop: 8,
  },

  // Modal
  modalSafe: { flex: 1 },
  modalHandle: {
    width: 40, height: 4, borderRadius: 2,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignSelf: 'center', marginTop: 12, marginBottom: 20,
  },
  modalScroll: { flex: 1, paddingHorizontal: 24 },
  modalTierBadge: {
    alignSelf: 'flex-start',
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 6, marginBottom: 14,
  },
  modalTierText: { fontSize: 10, fontWeight: '800', letterSpacing: 0.8 },
  modalTitle: {
    fontSize: 22, fontWeight: '800', color: '#fff',
    letterSpacing: -0.4, lineHeight: 28, marginBottom: 10,
  },
  modalMeta: { flexDirection: 'row', flexWrap: 'wrap', marginBottom: 20 },
  modalMetaText: { fontSize: 13, color: colors.grey },
  modalMetaDot: { fontSize: 13, color: 'rgba(255,255,255,0.25)' },
  modalResultBox: {
    backgroundColor: colors.greenDim,
    borderWidth: 1, borderColor: colors.greenBorder,
    borderRadius: 10, padding: 14, marginBottom: 20,
  },
  modalResultLabel: {
    fontSize: 9, fontWeight: '800', color: colors.green,
    letterSpacing: 1, marginBottom: 4,
  },
  modalResultText: { fontSize: 16, fontWeight: '700', color: '#fff' },
  rule: { height: 1, backgroundColor: colors.border, marginBottom: 20 },
  modalSectionLabel: {
    fontSize: 10, fontWeight: '700', color: colors.grey,
    letterSpacing: 1.2, textTransform: 'uppercase', marginBottom: 8,
  },
  modalOneLiner: { fontSize: 16, color: '#fff', lineHeight: 24, fontWeight: '500' },
  modalContext: { fontSize: 14, color: colors.body, lineHeight: 22 },
  quoteBox: {
    marginTop: 20,
    borderLeftWidth: 2, borderLeftColor: colors.green,
    paddingLeft: 14, paddingVertical: 4,
  },
  quoteText: { fontSize: 13, color: colors.grey, fontStyle: 'italic', lineHeight: 20 },
  pmid: { marginTop: 16, fontSize: 12, color: 'rgba(255,255,255,0.3)' },
  modalCloseBtn: {
    margin: 16,
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 12, paddingVertical: 16,
    alignItems: 'center',
  },
  modalCloseBtnText: { fontSize: 15, fontWeight: '700', color: '#fff' },
});
