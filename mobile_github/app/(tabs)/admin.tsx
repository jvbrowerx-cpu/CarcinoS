import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert as RNAlert,
  Modal,
  SafeAreaView as RNSafeArea,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useState, useEffect } from 'react';
import { colors, tiers, TierCode } from '../../constants/theme';
import { Alert, DEMO_EXTRACTED } from '../../lib/demo-data';
import {
  fetchExtractedAlerts,
  updateAlertStatus,
  publishApproved,
  DEMO_MODE,
} from '../../lib/supabase';

// ── Types ────────────────────────────────────────────────────────────────────

type Decision = 'APPROVED' | 'REJECTED' | null;

interface LocalAlert extends Alert {
  _decision?: Decision;
  _editedOneLiner?: string;
}

// ── Edit modal ───────────────────────────────────────────────────────────────

function EditModal({
  alert,
  onSave,
  onClose,
}: {
  alert: LocalAlert;
  onSave: (oneLiner: string, tier: TierCode) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(alert._editedOneLiner ?? alert.one_liner);
  const [tier, setTier] = useState<TierCode>(alert.tier);

  return (
    <Modal animationType="slide" presentationStyle="formSheet" onRequestClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={{ flex: 1 }}
      >
        <RNSafeArea style={[styles.editModalSafe, { backgroundColor: colors.cardBg }]}>
          <View style={styles.editModalHeader}>
            <Text style={styles.editModalTitle}>Edit Alert</Text>
            <TouchableOpacity onPress={onClose}>
              <Ionicons name="close" size={24} color={colors.grey} />
            </TouchableOpacity>
          </View>

          <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 20 }}>
            {/* Tier selector */}
            <Text style={styles.editLabel}>TIER</Text>
            <View style={styles.tierRow}>
              {(['PI', 'INC', 'HOR'] as TierCode[]).map((t) => {
                const td = tiers[t];
                const active = tier === t;
                return (
                  <TouchableOpacity
                    key={t}
                    style={[
                      styles.tierChip,
                      { borderColor: active ? td.bg : 'rgba(255,255,255,0.15)' },
                      active && { backgroundColor: td.bg },
                    ]}
                    onPress={() => setTier(t)}
                  >
                    <Text style={[
                      styles.tierChipText,
                      { color: active ? td.text : colors.grey },
                    ]}>
                      {t}
                    </Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            {/* One-liner editor */}
            <Text style={[styles.editLabel, { marginTop: 20 }]}>ONE-LINER</Text>
            <TextInput
              style={styles.editInput}
              value={text}
              onChangeText={setText}
              multiline
              numberOfLines={4}
              placeholderTextColor={colors.greyDim}
              placeholder="Clinical one-liner…"
              selectionColor={colors.green}
            />

            <TouchableOpacity
              style={styles.saveBtn}
              onPress={() => onSave(text, tier)}
            >
              <Text style={styles.saveBtnText}>Save Changes</Text>
            </TouchableOpacity>
          </ScrollView>
        </RNSafeArea>
      </KeyboardAvoidingView>
    </Modal>
  );
}

// ── Queue card ───────────────────────────────────────────────────────────────

function QueueCard({
  alert,
  onApprove,
  onReject,
  onEdit,
}: {
  alert: LocalAlert;
  onApprove: () => void;
  onReject: () => void;
  onEdit: () => void;
}) {
  const tier = tiers[alert.tier];
  const decision = alert._decision;

  return (
    <View
      style={[
        styles.qCard,
        decision === 'APPROVED' && styles.qCardApproved,
        decision === 'REJECTED' && styles.qCardRejected,
      ]}
    >
      {/* Tier tag + title */}
      <View style={styles.qCardTop}>
        <View style={[styles.qTierTag, { backgroundColor: tier.bg }]}>
          <Text style={[styles.qTierTagText, { color: tier.text }]}>{tier.shortLabel}</Text>
        </View>
        <Text style={styles.qTitle}>{alert.title}</Text>
      </View>

      {/* Meta */}
      <Text style={styles.qMeta}>
        {alert.journal}{alert.phase ? ` · ${alert.phase}` : ''} · {alert.disease_site}
      </Text>

      {/* One-liner */}
      <Text style={styles.qOneLiner}>{alert._editedOneLiner ?? alert.one_liner}</Text>

      {/* Key result */}
      {alert.result && (
        <View style={styles.qResultRow}>
          <Text style={styles.qResultLabel}>RESULT </Text>
          <Text style={styles.qResultText}>{alert.result}</Text>
        </View>
      )}

      {/* Action buttons */}
      <View style={styles.qActions}>
        <TouchableOpacity
          style={[
            styles.qBtn,
            styles.qBtnApprove,
            decision === 'APPROVED' && styles.qBtnActive,
          ]}
          onPress={onApprove}
        >
          <Ionicons
            name="checkmark-circle"
            size={15}
            color={decision === 'APPROVED' ? '#fff' : colors.approved}
          />
          <Text style={[
            styles.qBtnText,
            { color: decision === 'APPROVED' ? '#fff' : colors.approved },
          ]}>
            {decision === 'APPROVED' ? 'Approved' : 'Approve'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[
            styles.qBtn,
            styles.qBtnReject,
            decision === 'REJECTED' && styles.qBtnRejectActive,
          ]}
          onPress={onReject}
        >
          <Ionicons
            name="close-circle"
            size={15}
            color={decision === 'REJECTED' ? '#fff' : colors.rejected}
          />
          <Text style={[
            styles.qBtnText,
            { color: decision === 'REJECTED' ? '#fff' : colors.rejected },
          ]}>
            {decision === 'REJECTED' ? 'Rejected' : 'Reject'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity style={[styles.qBtn, styles.qBtnEdit]} onPress={onEdit}>
          <Ionicons name="pencil" size={13} color={colors.grey} />
          <Text style={[styles.qBtnText, { color: colors.grey }]}>Edit</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

// ── Screen ───────────────────────────────────────────────────────────────────

export default function AdminScreen() {
  const [queue, setQueue] = useState<LocalAlert[]>([]);
  const [editing, setEditing] = useState<LocalAlert | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    fetchExtractedAlerts()
      .then((data) => setQueue(data as LocalAlert[]))
      .catch(console.error);
  }, []);

  const approvedCount = queue.filter((a) => a._decision === 'APPROVED').length;
  const pendingCount = queue.filter((a) => !a._decision).length;

  function decide(id: string, decision: Decision) {
    setQueue((prev) =>
      prev.map((a) => (a.id === id ? { ...a, _decision: a._decision === decision ? null : decision } : a))
    );
    if (!DEMO_MODE) {
      updateAlertStatus(id, decision === 'APPROVED' ? 'APPROVED' : 'REJECTED').catch(console.error);
    }
  }

  function saveEdit(id: string, oneLiner: string, tier: TierCode) {
    setQueue((prev) =>
      prev.map((a) => (a.id === id ? { ...a, _editedOneLiner: oneLiner, tier } : a))
    );
    setEditing(null);
  }

  function handlePublish() {
    if (approvedCount === 0) {
      RNAlert.alert('Nothing to publish', 'Approve at least one alert first.');
      return;
    }
    RNAlert.alert(
      'Publish digest?',
      `This will publish ${approvedCount} approved alert${approvedCount > 1 ? 's' : ''} to the clinician feed.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Publish',
          style: 'default',
          onPress: async () => {
            setPublishing(true);
            try {
              if (!DEMO_MODE) await publishApproved();
              setQueue((prev) =>
                prev.map((a) =>
                  a._decision === 'APPROVED' ? { ...a, status: 'PUBLISHED', _decision: undefined } : a
                )
              );
              RNAlert.alert('Published', `${approvedCount} alert${approvedCount > 1 ? 's' : ''} published successfully.`);
            } catch (e) {
              RNAlert.alert('Error', 'Publish failed. Check your connection.');
            } finally {
              setPublishing(false);
            }
          },
        },
      ]
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      {/* Nav */}
      <View style={styles.nav}>
        <View style={styles.navLeft}>
          <View style={styles.logoBox}>
            <Text style={styles.logoText}>C<Text style={{ color: colors.green }}>S</Text></Text>
          </View>
          <View>
            <Text style={styles.brandName}>
              Carcino<Text style={{ color: colors.green }}>S</Text>
            </Text>
          </View>
          <View style={styles.editorBadge}>
            <Text style={styles.editorBadgeText}>EDITOR</Text>
          </View>
        </View>
        {DEMO_MODE && (
          <View style={styles.demoBadge}>
            <Text style={styles.demoBadgeText}>DEMO</Text>
          </View>
        )}
      </View>

      {/* Stats row */}
      <View style={styles.statsRow}>
        <View style={styles.statBlock}>
          <Text style={styles.statNum}>{queue.length}</Text>
          <Text style={styles.statLabel}>In queue</Text>
        </View>
        <View style={[styles.statBlock, styles.statDivider]}>
          <Text style={[styles.statNum, { color: colors.pending }]}>{pendingCount}</Text>
          <Text style={styles.statLabel}>Pending</Text>
        </View>
        <View style={[styles.statBlock, styles.statDivider]}>
          <Text style={[styles.statNum, { color: colors.approved }]}>{approvedCount}</Text>
          <Text style={styles.statLabel}>Approved</Text>
        </View>
      </View>

      {/* Queue list */}
      <ScrollView
        style={styles.scroll}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
      >
        <Text style={styles.queueHeading}>Review Queue</Text>

        {queue.length === 0 && (
          <View style={styles.empty}>
            <Ionicons name="checkmark-done-circle-outline" size={40} color={colors.green} />
            <Text style={styles.emptyText}>Queue is empty</Text>
          </View>
        )}

        {queue.map((alert) => (
          <QueueCard
            key={alert.id}
            alert={alert}
            onApprove={() => decide(alert.id, 'APPROVED')}
            onReject={() => decide(alert.id, 'REJECTED')}
            onEdit={() => setEditing(alert)}
          />
        ))}

        <View style={{ height: 20 }} />
      </ScrollView>

      {/* Publish bar */}
      <View style={styles.publishBar}>
        <TouchableOpacity
          style={[
            styles.publishBtn,
            approvedCount === 0 && styles.publishBtnDisabled,
          ]}
          onPress={handlePublish}
          disabled={publishing}
        >
          <Ionicons
            name="send"
            size={16}
            color={approvedCount === 0 ? colors.grey : '#fff'}
          />
          <Text style={[
            styles.publishBtnText,
            approvedCount === 0 && { color: colors.grey },
          ]}>
            {publishing ? 'Publishing…' : `Publish Digest${approvedCount > 0 ? ` (${approvedCount})` : ''}`}
          </Text>
        </TouchableOpacity>
      </View>

      {editing && (
        <EditModal
          alert={editing}
          onSave={(oneLiner, tier) => saveEdit(editing.id, oneLiner, tier)}
          onClose={() => setEditing(null)}
        />
      )}
    </SafeAreaView>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },

  // Nav
  nav: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingVertical: 14,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: 'rgba(6,6,9,0.92)',
  },
  navLeft: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  logoBox: {
    width: 32, height: 32,
    borderWidth: 1.5, borderColor: 'rgba(255,255,255,0.6)',
    borderRadius: 7, backgroundColor: 'rgba(255,255,255,0.04)',
    alignItems: 'center', justifyContent: 'center',
  },
  logoText: { fontFamily: 'Georgia', fontSize: 13, fontWeight: '800', color: '#fff' },
  brandName: { fontSize: 16, fontWeight: '700', color: '#fff', letterSpacing: -0.3 },
  editorBadge: {
    backgroundColor: colors.greenDim,
    borderWidth: 1, borderColor: colors.greenBorder,
    borderRadius: 5, paddingHorizontal: 7, paddingVertical: 3,
  },
  editorBadgeText: { fontSize: 9, fontWeight: '800', color: colors.green, letterSpacing: 1 },
  demoBadge: {
    backgroundColor: 'rgba(240,168,67,0.15)',
    borderWidth: 1, borderColor: 'rgba(240,168,67,0.4)',
    borderRadius: 4, paddingHorizontal: 6, paddingVertical: 2,
  },
  demoBadgeText: { fontSize: 9, fontWeight: '800', color: colors.pending, letterSpacing: 0.8 },

  // Stats
  statsRow: {
    flexDirection: 'row',
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  statBlock: {
    flex: 1, alignItems: 'center', paddingVertical: 14,
  },
  statDivider: {
    borderLeftWidth: 1, borderLeftColor: colors.border,
  },
  statNum: { fontSize: 22, fontWeight: '800', color: '#fff', letterSpacing: -0.5 },
  statLabel: { fontSize: 11, color: colors.grey, marginTop: 2 },

  // Scroll
  scroll: { flex: 1 },
  scrollContent: { padding: 16, paddingBottom: 16 },
  queueHeading: {
    fontSize: 13, fontWeight: '700', color: colors.grey,
    textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12,
  },

  // Queue card
  qCard: {
    backgroundColor: colors.cardBg,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: 14, padding: 16, marginBottom: 12,
  },
  qCardApproved: {
    borderColor: 'rgba(76,175,125,0.4)',
    backgroundColor: 'rgba(76,175,125,0.06)',
  },
  qCardRejected: {
    borderColor: 'rgba(224,92,92,0.3)',
    backgroundColor: 'rgba(224,92,92,0.04)',
    opacity: 0.7,
  },
  qCardTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, marginBottom: 8 },
  qTierTag: {
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 5,
  },
  qTierTagText: { fontSize: 9, fontWeight: '800', letterSpacing: 0.6 },
  qTitle: { flex: 1, fontSize: 14, fontWeight: '700', color: '#fff', lineHeight: 20 },
  qMeta: { fontSize: 11, color: colors.grey, marginBottom: 8 },
  qOneLiner: { fontSize: 13, color: colors.body, lineHeight: 19, marginBottom: 8 },
  qResultRow: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  qResultLabel: { fontSize: 10, fontWeight: '800', color: colors.grey, letterSpacing: 1 },
  qResultText: { fontSize: 12, color: '#fff', fontWeight: '600' },
  qActions: { flexDirection: 'row', gap: 8, marginTop: 4 },
  qBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 5,
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: 8, borderWidth: 1, flex: 1, justifyContent: 'center',
  },
  qBtnApprove: {
    borderColor: 'rgba(76,175,125,0.35)',
    backgroundColor: 'rgba(76,175,125,0.08)',
  },
  qBtnActive: {
    backgroundColor: colors.approved,
    borderColor: colors.approved,
  },
  qBtnReject: {
    borderColor: 'rgba(224,92,92,0.35)',
    backgroundColor: 'rgba(224,92,92,0.08)',
  },
  qBtnRejectActive: {
    backgroundColor: colors.rejected,
    borderColor: colors.rejected,
  },
  qBtnEdit: {
    flex: 0, paddingHorizontal: 14,
    borderColor: colors.border,
    backgroundColor: 'rgba(255,255,255,0.05)',
  },
  qBtnText: { fontSize: 12, fontWeight: '700' },

  // Empty state
  empty: { alignItems: 'center', paddingVertical: 60, gap: 12 },
  emptyText: { fontSize: 16, color: colors.grey, fontWeight: '600' },

  // Publish bar
  publishBar: {
    padding: 16, paddingBottom: Platform.OS === 'ios' ? 8 : 16,
    borderTopWidth: 1, borderTopColor: colors.border,
    backgroundColor: 'rgba(6,6,9,0.95)',
  },
  publishBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8,
    backgroundColor: colors.greenMuted,
    borderRadius: 12, paddingVertical: 16,
  },
  publishBtnDisabled: {
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  publishBtnText: { fontSize: 15, fontWeight: '700', color: '#fff' },

  // Edit modal
  editModalSafe: { flex: 1 },
  editModalHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 20, paddingTop: 20, paddingBottom: 16,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  editModalTitle: { fontSize: 17, fontWeight: '700', color: '#fff' },
  editLabel: {
    fontSize: 10, fontWeight: '700', color: colors.grey,
    letterSpacing: 1.2, marginBottom: 10,
  },
  tierRow: { flexDirection: 'row', gap: 10 },
  tierChip: {
    flex: 1, paddingVertical: 10, borderRadius: 8,
    borderWidth: 1.5, alignItems: 'center',
  },
  tierChipText: { fontSize: 12, fontWeight: '800', letterSpacing: 0.5 },
  editInput: {
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderWidth: 1, borderColor: 'rgba(255,255,255,0.14)',
    borderRadius: 10, padding: 14,
    fontSize: 15, color: '#fff', lineHeight: 22,
    minHeight: 120, textAlignVertical: 'top',
  },
  saveBtn: {
    backgroundColor: colors.greenMuted,
    borderRadius: 12, paddingVertical: 15,
    alignItems: 'center', marginTop: 20,
  },
  saveBtnText: { fontSize: 15, fontWeight: '700', color: '#fff' },
});
