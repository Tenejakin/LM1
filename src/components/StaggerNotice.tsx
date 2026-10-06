import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';

/**
 * Staggered capture keeps the upper camera half a frame behind the lower one. If that offset drifts
 * or is being restored the Pi stops arming, and this says why and what to do. Nothing shows in the
 * normal in-step mode or while the offset is healthy.
 */
export function StaggerNotice() {
  const { status } = useLaunchMonitor();
  const camera = status?.camera;
  if (camera?.syncMode !== 'stagger' && camera?.staggerState !== 'failed') return null;
  const state = camera.staggerState;
  if (state === 'locked' || state === 'locking' || state === undefined) return null;
  const copy = {
    'drift-soon': { tone: 'warn', title: 'Cameras drifting', body: 'The two cameras are drifting out of step. They will re-sync on their own the next time the mat is clear.' },
    resyncing: { tone: 'block', title: 'Cameras re-syncing', body: 'Ball detection is paused for a few seconds while the cameras re-align. Keep the mat clear.' },
    drifted: { tone: 'block', title: 'Cameras out of step', body: 'Ball detection is paused. Take the ball off the mat and the cameras will re-sync by themselves.' },
    failed: { tone: 'block', title: 'Could not hold the cameras in step', body: 'Running without the second camera pairing. Restart the Pi if this stays; it retries every 30 seconds while the mat is clear.' },
  }[state];
  if (!copy) return null;
  const blocked = copy.tone === 'block';
  return (
    <View accessibilityRole="alert" style={[styles.card, blocked && styles.cardBlocked]}>
      <Ionicons name={blocked ? 'pause-circle' : 'alert-circle-outline'} size={20} color={blocked ? colors.orange : colors.textMuted} />
      <View style={styles.copy}>
        <Text style={styles.title}>{copy.title}</Text>
        <Text style={styles.body}>{copy.body}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    alignItems: 'flex-start', backgroundColor: colors.surface, borderColor: colors.line, borderRadius: radii.md,
    borderWidth: 1, flexDirection: 'row', gap: 10, marginBottom: spacing.sm, padding: spacing.md,
  },
  cardBlocked: { backgroundColor: '#2A2114', borderColor: '#5A4522' },
  copy: { flex: 1, gap: 2 },
  title: { color: colors.text, fontSize: 14, fontWeight: '800' },
  body: { color: colors.textMuted, fontSize: 12, lineHeight: 17 },
});
