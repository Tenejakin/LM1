import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, fonts } from '@/theme';
import { AppTab } from '@/types';

export type PlayMode = 'swing' | 'putting';

const playModes: { key: PlayMode; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: 'swing', label: 'Full swing', icon: 'radio' },
  { key: 'putting', label: 'Putting', icon: 'golf' },
];

const tabs: {
  key: AppTab;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  activeIcon: keyof typeof Ionicons.glyphMap;
}[] = [
  { key: 'home', label: 'Play', icon: 'radio-outline', activeIcon: 'radio' },
  { key: 'calibration', label: 'Calibrate', icon: 'scan-outline', activeIcon: 'scan' },
  { key: 'history', label: 'Sessions', icon: 'stats-chart-outline', activeIcon: 'stats-chart' },
  { key: 'device', label: 'Device', icon: 'hardware-chip-outline', activeIcon: 'hardware-chip' },
  { key: 'cloud', label: 'Cloud', icon: 'cloud-outline', activeIcon: 'cloud' },
];

export function BottomNav({
  active,
  onChange,
  playMode,
  onPlayModeChange,
}: {
  active: AppTab;
  onChange: (tab: AppTab) => void;
  playMode: PlayMode;
  onPlayModeChange: (mode: PlayMode) => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <View style={styles.wrap}>
      {active === 'home' ? (
        <View style={styles.modeBar}>
          {playModes.map((mode) => {
            const selected = mode.key === playMode;
            return (
              <Pressable
                key={mode.key}
                accessibilityRole="radio"
                accessibilityLabel={mode.label}
                accessibilityState={{ selected }}
                onPress={() => onPlayModeChange(mode.key)}
                style={({ pressed }) => [styles.mode, selected && styles.modeSelected, pressed && styles.pressed]}
              >
                <Ionicons name={mode.icon} size={14} color={selected ? colors.black : colors.textMuted} />
                <Text style={[styles.modeText, selected && styles.modeTextSelected]}>{mode.label}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
    <View style={[styles.container, { paddingBottom: Math.max(insets.bottom, 8) }]}>
      {tabs.map((tab) => {
        const selected = tab.key === active;
        const label = tab.key === 'home' ? (playMode === 'putting' ? 'Putting' : 'Swing') : tab.label;
        return (
          <Pressable
            key={tab.key}
            accessibilityRole="tab"
            accessibilityLabel={tab.label}
            accessibilityState={{ selected }}
            onPress={() => onChange(tab.key)}
            style={({ pressed }) => [styles.tab, pressed && styles.pressed]}
          >
            <View style={[styles.indicator, selected && styles.indicatorActive]} />
            <Ionicons
              name={tab.key === 'home' && playMode === 'putting' ? (selected ? 'golf' : 'golf-outline') : selected ? tab.activeIcon : tab.icon}
              color={selected ? colors.text : colors.textDim}
              size={21}
            />
            <Text style={[styles.label, selected && styles.labelActive]}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { backgroundColor: colors.background },
  modeBar: {
    borderTopColor: colors.line,
    borderTopWidth: 1,
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 16,
    paddingTop: 10,
  },
  mode: {
    alignItems: 'center',
    borderColor: colors.lineStrong,
    borderRadius: 4,
    borderWidth: 1,
    flex: 1,
    flexDirection: 'row',
    gap: 6,
    justifyContent: 'center',
    minHeight: 36,
  },
  modeSelected: { backgroundColor: colors.text, borderColor: colors.text },
  modeText: { color: colors.textMuted, fontFamily: fonts.mono, fontSize: 10, fontWeight: '600', letterSpacing: 1.4, textTransform: 'uppercase' },
  modeTextSelected: { color: colors.black },
  container: {
    alignItems: 'center',
    backgroundColor: colors.background,
    borderTopColor: colors.line,
    borderTopWidth: 1,
    flexDirection: 'row',
    justifyContent: 'space-around',
  },
  tab: {
    alignItems: 'center',
    flex: 1,
    gap: 4,
    justifyContent: 'center',
    minHeight: 58,
    paddingBottom: 4,
  },
  indicator: { alignSelf: 'stretch', backgroundColor: 'transparent', height: 2, marginBottom: 6, marginHorizontal: 10 },
  indicatorActive: { backgroundColor: colors.accent },
  pressed: { opacity: 0.6 },
  label: { color: colors.textDim, fontFamily: fonts.mono, fontSize: 8, fontWeight: '600', letterSpacing: 0.3, textTransform: 'uppercase' },
  labelActive: { color: colors.text },
});
