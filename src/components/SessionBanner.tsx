import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';

/** One line on the Monitor screen: where the next shot will be filed, and a tap to change it. */
export function SessionBanner({ onOpenSessions }: { onOpenSessions: () => void }) {
  const { activeSession, shots } = useLaunchMonitor();
  const count = activeSession ? shots.filter((shot) => shot.sessionId === activeSession.id).length : 0;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={activeSession ? `Session ${activeSession.name}, ${count} shots. Open sessions` : 'No session open. Open sessions to start one'}
      onPress={onOpenSessions}
      style={({ pressed }) => [styles.banner, !activeSession && styles.bannerIdle, pressed && styles.pressed]}
    >
      <View style={[styles.dot, !activeSession && styles.dotIdle]} />
      <Text numberOfLines={1} style={styles.text}>
        {activeSession
          ? <><Text style={styles.strong}>{activeSession.name}</Text> · {count} {count === 1 ? 'shot' : 'shots'}{activeSession.referenceDevice ? ` · vs ${activeSession.referenceDevice}` : ''}</>
          : 'No session open · shots are not being filed'}
      </Text>
      <Text style={styles.link}>{activeSession ? 'Sessions' : 'Start'}</Text>
      <Ionicons name="chevron-forward" size={14} color={colors.accent} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  banner: {
    alignItems: 'center', backgroundColor: '#152018', borderColor: '#24382A', borderRadius: radii.md, borderWidth: 1,
    flexDirection: 'row', gap: 8, marginBottom: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: 9,
  },
  bannerIdle: { backgroundColor: colors.surface, borderColor: colors.line },
  dot: { backgroundColor: colors.accent, borderRadius: 4, height: 8, width: 8 },
  dotIdle: { backgroundColor: colors.textDim },
  text: { color: colors.textMuted, flex: 1, fontSize: 12 },
  strong: { color: colors.text, fontWeight: '800' },
  link: { color: colors.accent, fontSize: 12, fontWeight: '800' },
  pressed: { opacity: 0.75 },
});
