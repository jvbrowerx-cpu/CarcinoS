import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors } from '../../constants/theme';

const ARCHIVES = [
  { label: 'Week of May 11, 2026', count: 8 },
  { label: 'Week of May 4, 2026', count: 6 },
  { label: 'Week of Apr 27, 2026', count: 7 },
  { label: 'Week of Apr 20, 2026', count: 5 },
  { label: 'Week of Apr 13, 2026', count: 9 },
];

export default function ArchiveScreen() {
  return (
    <SafeAreaView style={styles.safe} edges={['top']}>
      <View style={styles.nav}>
        <View style={styles.brand}>
          <View style={styles.logoBox}>
            <Text style={styles.logoText}>C<Text style={{ color: colors.green }}>S</Text></Text>
          </View>
          <Text style={styles.brandName}>Carcino<Text style={{ color: colors.green }}>S</Text></Text>
        </View>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.content}>
        <Text style={styles.heading}>Archive</Text>
        <Text style={styles.sub}>All published digests</Text>

        {ARCHIVES.map((item, i) => (
          <View key={i} style={styles.row}>
            <View>
              <Text style={styles.rowLabel}>{item.label}</Text>
              <Text style={styles.rowCount}>{item.count} alerts published</Text>
            </View>
            <Text style={styles.chevron}>›</Text>
          </View>
        ))}

        <Text style={styles.note}>
          Live archive connects once Supabase is configured.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
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
  scroll: { flex: 1 },
  content: { padding: 24, paddingBottom: 60 },
  heading: { fontSize: 26, fontWeight: '800', color: '#fff', letterSpacing: -0.5, marginBottom: 4 },
  sub: { fontSize: 14, color: colors.grey, marginBottom: 28 },
  row: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 18,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  rowLabel: { fontSize: 15, fontWeight: '600', color: '#fff', marginBottom: 2 },
  rowCount: { fontSize: 13, color: colors.grey },
  chevron: { fontSize: 22, color: 'rgba(255,255,255,0.3)' },
  note: {
    marginTop: 32, fontSize: 13, color: 'rgba(255,255,255,0.3)',
    textAlign: 'center', lineHeight: 20,
  },
});
