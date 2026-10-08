import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { clubs } from '@/data/clubs';
import { colors, radii, spacing } from '@/theme';
import { BagClub, ClubId } from '@/types';
import {
  bagClubFromDraft, BagClubDraft, draftFromBagClub, FACE_HEIGHT_RANGE_MM, FACE_MEASURING_GUIDE, FACE_WIDTH_RANGE_MM,
  MAX_BAG_CLUB_NAME,
} from '@/utils/bagClubs';

/** Add or edit a named club: its name, type, loft and measured face size. */
export function BagClubEditor({
  club, defaultClubId, visible, onClose, onSave, onDelete,
}: {
  club: BagClub | null;
  defaultClubId: ClubId;
  visible: boolean;
  onClose: () => void;
  onSave: (club: BagClub) => void;
  onDelete: (clubId: string) => void;
}) {
  const insets = useSafeAreaInsets();
  const [draft, setDraft] = useState<BagClubDraft>(() => draftFromBagClub(club, defaultClubId));
  const [error, setError] = useState<string | null>(null);
  const [guide, setGuide] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setDraft(draftFromBagClub(club, defaultClubId));
    setError(null);
    setConfirmDelete(false);
  }, [club, defaultClubId, visible]);

  const update = (key: keyof BagClubDraft) => (value: string) => setDraft((current) => ({ ...current, [key]: value }));
  const save = () => {
    const result = bagClubFromDraft(draft, club ?? undefined);
    if (typeof result === 'string') {
      setError(result);
      return;
    }
    onSave(result);
  };

  return (
    <Modal animationType="slide" onRequestClose={onClose} transparent visible={visible}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.root}>
        <Pressable accessibilityLabel="Close club editor" onPress={onClose} style={styles.backdrop} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
          <View style={styles.header}>
            <View>
              <Text style={styles.eyebrow}>My clubs</Text>
              <Text style={styles.title}>{club ? 'Edit club' : 'Add a club'}</Text>
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel="Close club editor" onPress={onClose} style={styles.close}>
              <Ionicons name="close" color={colors.text} size={20} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>Name</Text>
            <TextInput
              accessibilityLabel="Club name"
              autoFocus={!club}
              maxLength={MAX_BAG_CLUB_NAME}
              onChangeText={update('name')}
              placeholder="e.g. Vokey SM10 56.10 S"
              placeholderTextColor={colors.textDim}
              style={styles.input}
              value={draft.name}
            />

            <Text style={styles.label}>Club type</Text>
            <Text style={styles.hint}>Used for the flight and spin models; statistics stay separate per named club.</Text>
            <View style={styles.types}>
              {clubs.map((type) => {
                const selected = type.id === draft.baseClubId;
                return (
                  <Pressable
                    key={type.id}
                    accessibilityRole="radio"
                    accessibilityLabel={type.label}
                    accessibilityState={{ checked: selected }}
                    onPress={() => setDraft((current) => ({ ...current, baseClubId: type.id }))}
                    style={[styles.type, selected && styles.typeSelected]}
                  >
                    <Text style={[styles.typeText, selected && styles.typeTextSelected]}>{type.shortLabel}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={styles.label}>Loft (optional)</Text>
            <TextInput
              accessibilityLabel="Loft in degrees"
              keyboardType="decimal-pad"
              onChangeText={update('loftDeg')}
              placeholder="56"
              placeholderTextColor={colors.textDim}
              style={styles.input}
              value={draft.loftDeg}
            />

            <View style={styles.faceHeader}>
              <Text style={styles.label}>Face size (optional)</Text>
              <Pressable accessibilityRole="button" onPress={() => setGuide((open) => !open)} hitSlop={8}>
                <Text style={styles.link}>{guide ? 'Hide how to measure' : 'How to measure'}</Text>
              </Pressable>
            </View>
            {guide ? (
              <View style={styles.guide}>
                {FACE_MEASURING_GUIDE.map((line) => <Text key={line} style={styles.guideLine}>• {line}</Text>)}
              </View>
            ) : null}
            <View style={styles.faceRow}>
              <View style={styles.faceField}>
                <Text style={styles.hint}>Heel–toe width, mm ({FACE_WIDTH_RANGE_MM[0]}–{FACE_WIDTH_RANGE_MM[1]})</Text>
                <TextInput
                  accessibilityLabel="Face width in millimetres"
                  keyboardType="decimal-pad"
                  onChangeText={update('faceWidthMm')}
                  placeholder="78"
                  placeholderTextColor={colors.textDim}
                  style={styles.input}
                  value={draft.faceWidthMm}
                />
              </View>
              <View style={styles.faceField}>
                <Text style={styles.hint}>Face height, mm ({FACE_HEIGHT_RANGE_MM[0]}–{FACE_HEIGHT_RANGE_MM[1]})</Text>
                <TextInput
                  accessibilityLabel="Face height in millimetres"
                  keyboardType="decimal-pad"
                  onChangeText={update('faceHeightMm')}
                  placeholder="50"
                  placeholderTextColor={colors.textDim}
                  style={styles.input}
                  value={draft.faceHeightMm}
                />
              </View>
            </View>
            <Text style={styles.hint}>
              Strike location needs the face size and a camera view in which the clubhead stands out from the mat.
            </Text>

            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Pressable accessibilityRole="button" onPress={save} style={({ pressed }) => [styles.primary, pressed && styles.pressed]}>
              <Text style={styles.primaryText}>{club ? 'Save changes' : 'Add club'}</Text>
            </Pressable>
            {club ? (
              <Pressable
                accessibilityRole="button"
                accessibilityHint="Shots already hit with this club keep its name"
                onPress={() => (confirmDelete ? onDelete(club.id) : setConfirmDelete(true))}
                style={({ pressed }) => [styles.delete, pressed && styles.pressed]}
              >
                <Text style={styles.deleteText}>{confirmDelete ? 'Tap again to remove this club' : 'Remove club'}</Text>
              </Pressable>
            ) : null}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: '#000000B8' },
  sheet: {
    backgroundColor: colors.surface, borderColor: colors.lineStrong, borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl, borderWidth: 1, maxHeight: '92%', paddingHorizontal: spacing.md, paddingTop: spacing.md,
  },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  eyebrow: { color: colors.accent, fontSize: 10, fontWeight: '800', letterSpacing: 1.2, textTransform: 'uppercase' },
  title: { color: colors.text, fontSize: 24, fontWeight: '700', marginTop: 3 },
  close: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 6, height: 40, justifyContent: 'center', width: 40 },
  body: { gap: spacing.xs, paddingBottom: spacing.xl, paddingTop: spacing.md },
  label: { color: colors.text, fontSize: 13, fontWeight: '700', marginTop: spacing.sm },
  hint: { color: colors.textMuted, fontSize: 11, lineHeight: 16 },
  input: {
    backgroundColor: colors.background, borderColor: colors.line, borderRadius: radii.md, borderWidth: 1,
    color: colors.text, fontSize: 15, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  types: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  type: { backgroundColor: colors.surfaceRaised, borderColor: colors.line, borderRadius: radii.sm, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 7 },
  typeSelected: { backgroundColor: colors.accent, borderColor: colors.accent },
  typeText: { color: colors.textMuted, fontSize: 12, fontWeight: '800' },
  typeTextSelected: { color: colors.accentInk },
  faceHeader: { alignItems: 'flex-end', flexDirection: 'row', justifyContent: 'space-between' },
  link: { color: colors.accent, fontSize: 12, fontWeight: '700' },
  guide: { backgroundColor: colors.surfaceRaised, borderRadius: radii.sm, gap: 4, padding: spacing.sm },
  guideLine: { color: colors.textMuted, fontSize: 12, lineHeight: 17 },
  faceRow: { flexDirection: 'row', gap: spacing.sm },
  faceField: { flex: 1, gap: 4 },
  error: { color: colors.red, fontSize: 12, lineHeight: 18, marginTop: spacing.xs },
  primary: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.md, marginTop: spacing.md, paddingVertical: 13 },
  primaryText: { color: colors.accentInk, fontSize: 15, fontWeight: '800' },
  delete: { alignItems: 'center', marginTop: spacing.sm, paddingVertical: spacing.sm },
  deleteText: { color: colors.red, fontSize: 13, fontWeight: '700' },
  pressed: { opacity: 0.8 },
});
