import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radii } from '@/theme';
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
            style={({ pressed }) => [styles.tab, selected && styles.tabActive, pressed && styles.pressed]}
          >
            <Ionicons
              name={selected ? tab.activeIcon : tab.icon}
              color={selected ? colors.accent : colors.textDim}
              size={22}
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
    backgroundColor: '#0C1012F5',
    borderTopColor: colors.line,
    borderTopWidth: 1,
    flexDirection: 'row',
    gap: 2,
    justifyContent: 'space-around',
    paddingHorizontal: 6,
    paddingTop: 9,
  },
  tab: {
    alignItems: 'center',
    borderRadius: radii.md,
    flex: 1,
    gap: 3,
    justifyContent: 'center',
    minHeight: 56,
    paddingVertical: 4,
  },
  tabActive: { backgroundColor: '#1A2118' },
  pressed: { opacity: 0.7 },
  label: { color: colors.textDim, fontSize: 11, fontWeight: '700' },
  labelActive: { color: colors.accent },
});
