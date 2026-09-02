import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { clubCategories, clubs, getClub } from '@/data/clubs';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { colors, radii, spacing } from '@/theme';
import { ClubId } from '@/types';

export function ClubSelector({ disabled = false }: { disabled?: boolean }) {
  const { selectedClub, selectClub } = useLaunchMonitor();
  const [open, setOpen] = useState(false);
  const club = getClub(selectedClub);

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Selected club: ${club.label}. Change club`}
        accessibilityState={{ disabled }}
        disabled={disabled}
        onPress={() => setOpen(true)}
        style={({ pressed }) => [
          styles.selector,
          disabled && styles.selectorDisabled,
          pressed && styles.selectorPressed,
        ]}
      >
        <View style={styles.clubMark}>
          <Text style={styles.clubMarkText}>{club.shortLabel}</Text>
        </View>
        <View style={styles.selectorCopy}>
          <Text style={styles.selectorEyebrow}>Selected club</Text>
          <Text style={styles.selectorValue}>{club.label}</Text>
        </View>
        <View style={styles.changePill}>
          <Text style={styles.changeText}>{disabled ? 'Locked' : 'Change'}</Text>
          <Ionicons
            name={disabled ? 'lock-closed' : 'chevron-down'}
            size={14}
            color={disabled ? colors.textDim : colors.accent}
          />
        </View>
      </Pressable>

      <ClubPickerModal
        selectedClub={selectedClub}
        visible={open}
        onClose={() => setOpen(false)}
        onSelect={(clubId) => {
          selectClub(clubId);
          setOpen(false);
        }}
      />
    </>
  );
}

function ClubPickerModal({
  selectedClub,
  visible,
  onClose,
  onSelect,
}: {
  selectedClub: ClubId;
  visible: boolean;
  onClose: () => void;
  onSelect: (clubId: ClubId) => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal
      animationType="slide"
      onRequestClose={onClose}
      transparent
      visible={visible}
    >
      <View style={styles.modalRoot}>
        <Pressable accessibilityLabel="Close club selector" onPress={onClose} style={styles.backdrop} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
          <View style={styles.handle} />
          <View style={styles.sheetHeader}>
            <View>
              <Text style={styles.sheetEyebrow}>Before you swing</Text>
              <Text style={styles.sheetTitle}>Choose your club</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close club selector"
              onPress={onClose}
              style={styles.closeButton}
            >
              <Ionicons name="close" color={colors.text} size={20} />
            </Pressable>
          </View>
          <Text style={styles.sheetNote}>
            The selected club is saved with the shot and used by the estimated carry model.
          </Text>
          <ScrollView contentContainerStyle={styles.clubList} showsVerticalScrollIndicator={false}>
            {clubCategories.map((category) => (
              <View key={category} style={styles.category}>
                <Text style={styles.categoryTitle}>{category}</Text>
                <View style={styles.clubGrid}>
                  {clubs
                    .filter((club) => club.category === category)
                    .map((club) => {
                      const selected = club.id === selectedClub;
                      return (
                        <Pressable
                          key={club.id}
                          accessibilityRole="radio"
                          accessibilityLabel={club.label}
                          accessibilityState={{ checked: selected }}
                          onPress={() => onSelect(club.id)}
                          style={({ pressed }) => [
                            styles.clubOption,
                            selected && styles.clubOptionSelected,
                            pressed && styles.clubOptionPressed,
                          ]}
                        >
                          <Text style={[styles.clubOptionShort, selected && styles.clubOptionShortSelected]}>
                            {club.shortLabel}
                          </Text>
                          <Text style={[styles.clubOptionLabel, selected && styles.clubOptionLabelSelected]} numberOfLines={1}>
                            {club.label}
                          </Text>
                          {selected ? (
                            <Ionicons name="checkmark-circle" size={15} color={colors.accentInk} />
                          ) : null}
                        </Pressable>
                      );
                    })}
                </View>
              </View>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  selector: {
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderRadius: radii.md,
    borderWidth: 1,
    flexDirection: 'row',
    marginBottom: spacing.sm,
    minHeight: 66,
    paddingHorizontal: spacing.md,
  },
  selectorDisabled: { opacity: 0.72 },
  selectorPressed: { backgroundColor: colors.surfaceRaised, transform: [{ scale: 0.99 }] },
  clubMark: {
    alignItems: 'center',
    backgroundColor: '#1B241A',
    borderColor: '#34452F',
    borderRadius: 14,
    borderWidth: 1,
    height: 40,
    justifyContent: 'center',
    marginRight: 11,
    width: 44,
  },
  clubMarkText: { color: colors.accent, fontSize: 14, fontWeight: '900' },
  selectorCopy: { flex: 1 },
  selectorEyebrow: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.9, textTransform: 'uppercase' },
  selectorValue: { color: colors.text, fontSize: 16, fontWeight: '700', marginTop: 3 },
  changePill: { alignItems: 'center', flexDirection: 'row', gap: 4 },
  changeText: { color: colors.textMuted, fontSize: 11, fontWeight: '700' },
  modalRoot: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: '#000000B8' },
  sheet: {
    backgroundColor: colors.surface,
    borderColor: colors.lineStrong,
    borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl,
    borderWidth: 1,
    maxHeight: '86%',
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
  },
  handle: { alignSelf: 'center', backgroundColor: colors.lineStrong, borderRadius: 3, height: 4, marginBottom: spacing.md, width: 38 },
  sheetHeader: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  sheetEyebrow: { color: colors.accent, fontSize: 10, fontWeight: '800', letterSpacing: 1.2, textTransform: 'uppercase' },
  sheetTitle: { color: colors.text, fontSize: 27, fontWeight: '700', letterSpacing: -0.9, marginTop: 3 },
  closeButton: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 20, height: 40, justifyContent: 'center', width: 40 },
  sheetNote: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: spacing.sm, maxWidth: 330 },
  clubList: { paddingBottom: spacing.xl },
  category: { marginTop: spacing.lg },
  categoryTitle: { color: colors.textMuted, fontSize: 10, fontWeight: '900', letterSpacing: 1.1, marginBottom: spacing.sm, textTransform: 'uppercase' },
  clubGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  clubOption: {
    alignItems: 'center',
    backgroundColor: colors.surfaceRaised,
    borderColor: colors.line,
    borderRadius: radii.md,
    borderWidth: 1,
    minHeight: 72,
    paddingHorizontal: 7,
    paddingVertical: 9,
    width: '23%',
  },
  clubOptionSelected: { backgroundColor: colors.accent, borderColor: colors.accent },
  clubOptionPressed: { opacity: 0.75 },
  clubOptionShort: { color: colors.text, fontSize: 18, fontWeight: '900' },
  clubOptionShortSelected: { color: colors.accentInk },
  clubOptionLabel: { color: colors.textMuted, fontSize: 8, fontWeight: '700', marginTop: 3, maxWidth: '100%' },
  clubOptionLabelSelected: { color: '#44531D' },
});
