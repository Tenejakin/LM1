import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, fonts } from '@/theme';
import { AppTab } from '@/types';

const tabs: {
  key: AppTab;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  activeIcon: keyof typeof Ionicons.glyphMap;
}[] = [
  { key: 'home', label: 'Monitor', icon: 'radio-outline', activeIcon: 'radio' },
  { key: 'putting', label: 'Putting', icon: 'golf-outline', activeIcon: 'golf' },
  { key: 'calibration', label: 'Calibrate', icon: 'scan-outline', activeIcon: 'scan' },
  { key: 'history', label: 'Sessions', icon: 'stats-chart-outline', activeIcon: 'stats-chart' },
  { key: 'device', label: 'Device', icon: 'hardware-chip-outline', activeIcon: 'hardware-chip' },
  { key: 'cloud', label: 'Cloud', icon: 'cloud-outline', activeIcon: 'cloud' },
];

export function BottomNav({ active, onChange }: { active: AppTab; onChange: (tab: AppTab) => void }) {
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.container, { paddingBottom: Math.max(insets.bottom, 8) }]}>
      {tabs.map((tab) => {
        const selected = tab.key === active;
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
              name={selected ? tab.activeIcon : tab.icon}
              color={selected ? colors.text : colors.textDim}
              size={21}
            />
            <Text style={[styles.label, selected && styles.labelActive]}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
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
  label: { color: colors.textDim, fontFamily: fonts.mono, fontSize: 8.5, fontWeight: '600', letterSpacing: 0.9, textTransform: 'uppercase' },
  labelActive: { color: colors.text },
});
