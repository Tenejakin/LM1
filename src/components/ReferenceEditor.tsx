import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useUnits } from '@/context/UnitsContext';
import { colors, radii, spacing } from '@/theme';
import { ReferenceShotData, Shot } from '@/types';
import { draftFromReference, MAX_REFERENCE_DEVICE, MAX_REFERENCE_NOTES, ReferenceDraft, referenceFromDraft, Side } from '@/utils/referenceInput';

/**
 * Type in what another launch monitor showed for this swing. Numbers are entered in
 * the app's display units; left/right is a toggle so the sign convention never matters.
 */
export function ReferenceEditor({
  shot, defaultDevice, visible, onClose, onSave, onClear,
}: {
  shot: Shot;
  defaultDevice: string;
  visible: boolean;
  onClose: () => void;
  onSave: (reference: ReferenceShotData) => void;
  onClear: () => void;
}) {
  const insets = useSafeAreaInsets();
  const units = useUnits();
  const draftUnits = { speedUnit: units.speedUnit, distanceUnit: units.distanceUnit };
  const [draft, setDraft] = useState<ReferenceDraft>(() => draftFromReference(shot.reference, draftUnits, defaultDevice));
  const [error, setError] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setDraft(draftFromReference(shot.reference, { speedUnit: units.speedUnit, distanceUnit: units.distanceUnit }, defaultDevice));
    setError(null);
    setConfirmClear(false);
  }, [visible, shot.id, shot.reference, defaultDevice, units.speedUnit, units.distanceUnit]);

  const update = (key: keyof ReferenceDraft) => (value: string) => setDraft((current) => ({ ...current, [key]: value }));
  const side = (key: 'launchDirectionSide' | 'spinAxisSide' | 'clubPathSide') => (value: Side) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const save = () => {
    const result = referenceFromDraft(draft, draftUnits, shot.reference);
    if (typeof result === 'string') {
      setError(result);
      return;
    }
    onSave(result);
  };

  return (
    <Modal animationType="slide" onRequestClose={onClose} transparent visible={visible}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.root}>
        <Pressable accessibilityLabel="Close reference entry" onPress={onClose} style={styles.backdrop} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
          <View style={styles.header}>
            <View>
              <Text style={styles.eyebrow}>Shot #{shot.number}</Text>
              <Text style={styles.title}>{shot.reference ? 'Edit reference data' : 'Enter reference data'}</Text>
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel="Close reference entry" onPress={onClose} style={styles.close}>
              <Ionicons name="close" color={colors.text} size={20} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            <Text style={styles.hint}>
              Copy the numbers the other launch monitor shows for this same swing. Leave anything it did not report empty.
              Speeds in {units.speedLabel}, distances in {units.distanceLabel} (change under Device › Units).
            </Text>

            <Text style={styles.label}>Launch monitor</Text>
            <TextInput
              accessibilityLabel="Reference launch monitor name"
              maxLength={MAX_REFERENCE_DEVICE}
              onChangeText={update('device')}
              placeholder="GC3"
              placeholderTextColor={colors.textDim}
              style={styles.input}
              value={draft.device}
            />

            <Text style={styles.section}>Ball</Text>
            <View style={styles.row}>
              <Field label={`Ball speed (${units.speedLabel})`} value={draft.ballSpeed} onChange={update('ballSpeed')} placeholder="0" />
              <Field label="Launch angle (°)" value={draft.launchAngle} onChange={update('launchAngle')} placeholder="0" />
            </View>
            <SignedField
              label="Launch direction (°)" value={draft.launchDirection} onChange={update('launchDirection')}
              side={draft.launchDirectionSide} onSide={side('launchDirectionSide')} leftLabel="Left" rightLabel="Right"
            />
            <View style={styles.row}>
              <Field label="Backspin (rpm)" value={draft.spinRpm} onChange={update('spinRpm')} placeholder="0" integer />
            </View>
            <SignedField
              label="Spin axis (°)" value={draft.spinAxis} onChange={update('spinAxis')}
              side={draft.spinAxisSide} onSide={side('spinAxisSide')} leftLabel="Left (draw)" rightLabel="Right (fade)"
            />

            <Text style={styles.section}>Club</Text>
            <View style={styles.row}>
              <Field label={`Club speed (${units.speedLabel})`} value={draft.clubSpeed} onChange={update('clubSpeed')} placeholder="0" />
              <Field label="Attack angle (°, − down)" value={draft.attackAngle} onChange={update('attackAngle')} placeholder="0" signed />
            </View>
            <SignedField
              label="Club path (°)" value={draft.clubPath} onChange={update('clubPath')}
              side={draft.clubPathSide} onSide={side('clubPathSide')} leftLabel="Left (out-to-in)" rightLabel="Right (in-to-out)"
            />

            <Text style={styles.section}>Flight</Text>
            <View style={styles.row}>
              <Field label={`Carry (${units.distanceLabel})`} value={draft.carry} onChange={update('carry')} placeholder="0" />
              <Field label={`Total (${units.distanceLabel})`} value={draft.total} onChange={update('total')} placeholder="0" />
              <Field label={`Apex (${units.distanceLabel})`} value={draft.apex} onChange={update('apex')} placeholder="0" />
            </View>

            <Text style={styles.label}>Notes (optional)</Text>
            <TextInput
              accessibilityLabel="Reference notes"
              maxLength={MAX_REFERENCE_NOTES}
              multiline
              onChangeText={update('notes')}
              placeholder="e.g. thin strike, GC3 flagged low confidence"
              placeholderTextColor={colors.textDim}
              style={[styles.input, styles.notes]}
              value={draft.notes}
            />

            {error ? <Text style={styles.error}>{error}</Text> : null}
            <Pressable accessibilityRole="button" onPress={save} style={({ pressed }) => [styles.primary, pressed && styles.pressed]}>
              <Text style={styles.primaryText}>{shot.reference ? 'Save changes' : 'Save reference data'}</Text>
            </Pressable>
            {shot.reference ? (
              <Pressable
                accessibilityRole="button"
                onPress={() => (confirmClear ? onClear() : setConfirmClear(true))}
                style={({ pressed }) => [styles.clear, pressed && styles.pressed]}
              >
                <Text style={styles.clearText}>{confirmClear ? 'Tap again to remove the reference data' : 'Remove reference data'}</Text>
              </Pressable>
            ) : null}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

function Field({
  label, value, onChange, placeholder, integer = false, signed = false,
}: {
  label: string; value: string; onChange: (value: string) => void; placeholder?: string; integer?: boolean; signed?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        keyboardType={signed ? 'numbers-and-punctuation' : integer ? 'number-pad' : 'decimal-pad'}
        onChangeText={onChange}
        placeholder={placeholder}
        placeholderTextColor={colors.textDim}
        style={styles.input}
        value={value}
      />
    </View>
  );
}

function SignedField({
  label, value, onChange, side, onSide, leftLabel, rightLabel,
}: {
  label: string; value: string; onChange: (value: string) => void; side: Side; onSide: (side: Side) => void;
  leftLabel: string; rightLabel: string;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <View style={styles.signedRow}>
        <TextInput
          accessibilityLabel={label}
          keyboardType="decimal-pad"
          onChangeText={onChange}
          placeholder="0"
          placeholderTextColor={colors.textDim}
          style={[styles.input, styles.signedInput]}
          value={value}
        />
        {(['L', 'R'] as Side[]).map((option) => {
          const selected = side === option;
          return (
            <Pressable
              key={option}
              accessibilityRole="radio"
              accessibilityLabel={`${label} ${option === 'L' ? leftLabel : rightLabel}`}
              accessibilityState={{ checked: selected }}
              onPress={() => onSide(option)}
              style={[styles.side, selected && styles.sideSelected]}
            >
              <Text style={[styles.sideText, selected && styles.sideTextSelected]}>{option === 'L' ? leftLabel : rightLabel}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: '#000000B8' },
  sheet: {
    backgroundColor: colors.surface, borderColor: colors.lineStrong, borderTopLeftRadius: radii.xl,
    borderTopRightRadius: radii.xl, borderWidth: 1, maxHeight: '94%', paddingHorizontal: spacing.md, paddingTop: spacing.md,
  },
  header: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  eyebrow: { color: colors.accent, fontSize: 10, fontWeight: '800', letterSpacing: 1.2, textTransform: 'uppercase' },
  title: { color: colors.text, fontSize: 22, fontWeight: '700', marginTop: 3 },
  close: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 20, height: 40, justifyContent: 'center', width: 40 },
  body: { gap: spacing.xs, paddingBottom: spacing.xl, paddingTop: spacing.md },
  hint: { color: colors.textMuted, fontSize: 11, lineHeight: 16 },
  label: { color: colors.text, fontSize: 13, fontWeight: '700', marginTop: spacing.sm },
  section: { color: colors.accent, fontSize: 10, fontWeight: '800', letterSpacing: 1, marginTop: spacing.md, textTransform: 'uppercase' },
  row: { flexDirection: 'row', gap: spacing.sm },
  field: { flex: 1, gap: 4, minWidth: 0 },
  fieldLabel: { color: colors.textMuted, fontSize: 11, lineHeight: 16 },
  input: {
    backgroundColor: colors.background, borderColor: colors.line, borderRadius: radii.md, borderWidth: 1,
    color: colors.text, fontSize: 15, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  notes: { minHeight: 60, textAlignVertical: 'top' },
  signedRow: { alignItems: 'center', flexDirection: 'row', gap: 6 },
  signedInput: { flex: 1 },
  side: { backgroundColor: colors.surfaceRaised, borderColor: colors.line, borderRadius: radii.sm, borderWidth: 1, paddingHorizontal: 10, paddingVertical: 9 },
  sideSelected: { backgroundColor: colors.accent, borderColor: colors.accent },
  sideText: { color: colors.textMuted, fontSize: 11, fontWeight: '800' },
  sideTextSelected: { color: colors.accentInk },
  error: { color: colors.red, fontSize: 12, lineHeight: 18, marginTop: spacing.xs },
  primary: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.md, marginTop: spacing.md, paddingVertical: 13 },
  primaryText: { color: colors.accentInk, fontSize: 15, fontWeight: '800' },
  clear: { alignItems: 'center', marginTop: spacing.sm, paddingVertical: spacing.sm },
  clearText: { color: colors.red, fontSize: 13, fontWeight: '700' },
  pressed: { opacity: 0.8 },
});
