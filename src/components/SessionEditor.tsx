import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useState } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radii, spacing } from '@/theme';
import { PracticeSession } from '@/types';
import { defaultSessionName, MAX_SESSION_NAME } from '@/utils/sessions';

export interface SessionDraft {
  name: string;
  referenceDevice: string;
  notes: string;
}

/** Start a new session or edit an existing one: a name, the reference monitor in use and notes. */
export function SessionEditor({
  session, visible, onClose, onSave, onDelete,
}: {
  /** Null starts a new session. */
  session: PracticeSession | null;
  visible: boolean;
  onClose: () => void;
  onSave: (draft: SessionDraft) => void;
  onDelete?: (sessionId: string) => void;
}) {
  const insets = useSafeAreaInsets();
  const [draft, setDraft] = useState<SessionDraft>({ name: '', referenceDevice: 'GC3', notes: '' });
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setDraft({
      name: session?.name ?? '',
      referenceDevice: session?.referenceDevice ?? 'GC3',
      notes: session?.notes ?? '',
    });
    setConfirmDelete(false);
  }, [visible, session]);

  const update = (key: keyof SessionDraft) => (value: string) => setDraft((current) => ({ ...current, [key]: value }));

  return (
    <Modal animationType="slide" onRequestClose={onClose} transparent visible={visible}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.root}>
        <Pressable accessibilityLabel="Close session editor" onPress={onClose} style={styles.backdrop} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, spacing.md) }]}>
          <View style={styles.header}>
            <View>
              <Text style={styles.eyebrow}>Sessions</Text>
              <Text style={styles.title}>{session ? 'Edit session' : 'Start a session'}</Text>
            </View>
            <Pressable accessibilityRole="button" accessibilityLabel="Close session editor" onPress={onClose} style={styles.close}>
              <Ionicons name="close" color={colors.text} size={20} />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            <Text style={styles.label}>Name</Text>
            <TextInput
              accessibilityLabel="Session name"
              autoFocus={!session}
              maxLength={MAX_SESSION_NAME}
              onChangeText={update('name')}
              placeholder={defaultSessionName()}
              placeholderTextColor={colors.textDim}
              style={styles.input}
              value={draft.name}
            />
            <Text style={styles.hint}>Every shot hit while the session is open is filed under it, so a test day or a club comparison stays together.</Text>

            <Text style={styles.label}>Reference launch monitor (optional)</Text>
            <TextInput
              accessibilityLabel="Reference launch monitor for this session"
              maxLength={30}
              onChangeText={update('referenceDevice')}
              placeholder="GC3"
              placeholderTextColor={colors.textDim}
              style={styles.input}
              value={draft.referenceDevice}
            />
            <Text style={styles.hint}>Offered as the device name when you type in another monitor&apos;s numbers for a shot.</Text>

            <Text style={styles.label}>Notes (optional)</Text>
            <TextInput
              accessibilityLabel="Session notes"
              maxLength={300}
              multiline
              onChangeText={update('notes')}
              placeholder="Mat, balls, lighting, who was hitting…"
              placeholderTextColor={colors.textDim}
              style={[styles.input, styles.notes]}
              value={draft.notes}
            />

            <Pressable accessibilityRole="button" onPress={() => onSave(draft)} style={({ pressed }) => [styles.primary, pressed && styles.pressed]}>
              <Text style={styles.primaryText}>{session ? 'Save changes' : 'Start session'}</Text>
            </Pressable>
            {session && onDelete ? (
              <Pressable
                accessibilityRole="button"
                accessibilityHint="Shots stay in history without a session"
                onPress={() => (confirmDelete ? onDelete(session.id) : setConfirmDelete(true))}
                style={({ pressed }) => [styles.delete, pressed && styles.pressed]}
              >
                <Text style={styles.deleteText}>{confirmDelete ? 'Tap again to delete this session' : 'Delete session'}</Text>
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
  close: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 20, height: 40, justifyContent: 'center', width: 40 },
  body: { gap: spacing.xs, paddingBottom: spacing.xl, paddingTop: spacing.md },
  label: { color: colors.text, fontSize: 13, fontWeight: '700', marginTop: spacing.sm },
  hint: { color: colors.textMuted, fontSize: 11, lineHeight: 16 },
  input: {
    backgroundColor: colors.background, borderColor: colors.line, borderRadius: radii.md, borderWidth: 1,
    color: colors.text, fontSize: 15, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  notes: { minHeight: 70, textAlignVertical: 'top' },
  primary: { alignItems: 'center', backgroundColor: colors.accent, borderRadius: radii.md, marginTop: spacing.md, paddingVertical: 13 },
  primaryText: { color: colors.accentInk, fontSize: 15, fontWeight: '800' },
  delete: { alignItems: 'center', marginTop: spacing.sm, paddingVertical: spacing.sm },
  deleteText: { color: colors.red, fontSize: 13, fontWeight: '700' },
  pressed: { opacity: 0.8 },
});
